import os
import sys
from pathlib import Path
import unittest
import json
import base64
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
import main as rail_main  # noqa: E402
from decide import GrantSnapshot  # noqa: E402
from test_asa import _sign  # noqa: E402


class HttpBoundaryTests(unittest.TestCase):
  def setUp(self):
    self.env = patch.dict(
      os.environ,
      {
        "VALKEY_URL": "",
        "ALLOW_MEMORY_RAIL": "1",
        "WEBHOOK_INTERNAL_TOKEN": "internal-" + "a" * 32,
        "WEBHOOK_CHARGE_TOKEN": "merchant-" + "b" * 32,
      },
    )
    self.env.start()
    self.client = TestClient(app)
    self.client.__enter__()

  def tearDown(self):
    self.client.__exit__(None, None, None)
    self.env.stop()

  def test_no_silent_memory_fallback(self):
    with patch.dict(os.environ, {"VALKEY_URL": "", "ALLOW_MEMORY_RAIL": ""}):
      with TestClient(app) as client:
        self.assertEqual(client.get("/readyz").status_code, 503)

  def test_asa_requires_key_and_signature_and_bounded_body(self):
    with patch.dict(os.environ, {"LITHIC_ASA_SECRET": ""}):
      self.assertEqual(self.client.post("/lithic/asa", json={}).status_code, 503)
    with patch.dict(os.environ, {"LITHIC_ASA_SECRET": base64.b64encode(b"test-secret").decode()}):
      self.assertEqual(self.client.post("/lithic/asa", json={}).status_code, 401)
      self.assertEqual(self.client.post("/lithic/asa", content=b"x" * 131073).status_code, 413)

  def test_signed_asa_cannot_approve_without_trusted_checkout_correlation(self):
    grant = GrantSnapshot(
      "grt_asa",
      "ISSUED",
      "mnd_asa",
      1,
      "ins_asa",
      "VOLT SUPPLY CO",
      "5732",
      2999,
      "USD",
      datetime.now(timezone.utc) + timedelta(minutes=1),
      user_id="usr_asa",
      mandate_hash="a" * 64,
      checkout_id="chk_charger",
      checkout_hash="b" * 64,
      merchant_binding_id="bind_asa",
    )
    store = rail_main._store
    store.set_mandate(grant.mandate_id, status="active", version=1)
    store.put_grant(grant)
    payload = {
      "token": "transaction-1",
      "status": "AUTHORIZATION",
      "card": {"token": "ins_asa"},
      "merchant": {"descriptor": "VOLT SUPPLY CO", "mcc": "5732"},
      "amounts": {"merchant": {"amount": 2999, "currency": "USD"}},
    }

    def request(data):
      body = json.dumps(data).encode()
      ts = str(int(time.time()))
      key = b"test-secret"
      return self.client.post(
        "/lithic/asa",
        content=body,
        headers={
          "webhook-id": "msg_asa",
          "webhook-timestamp": ts,
          "webhook-signature": _sign(key, "msg_asa", ts, body),
        },
      )

    with patch.dict(os.environ, {"LITHIC_ASA_SECRET": base64.b64encode(b"test-secret").decode()}):
      first = request(payload)
      self.assertEqual(first.status_code, 200, first.text)
      self.assertNotEqual(first.json()["result"], "APPROVED")
      self.assertEqual(first.json()["token"], "transaction-1")
      self.assertEqual(request(payload).json(), first.json())
      self.assertEqual(
        request(
          {**payload, "amounts": {"merchant": {"amount": 2998, "currency": "USD"}}}
        ).status_code,
        409,
      )
    self.assertEqual(store.get_grant(grant.grant_id).status, "ISSUED")
    self.assertIsNone(store.get_event("msg_asa"))
    self.assertEqual(
      store.get_event("msg_asa", event_scope="lithic").decision.rail, "lithic_sandbox"
    )

  def test_card_control_cannot_open_or_claim_unconfirmed_pause(self):
    headers = {"Authorization": "Bearer " + os.environ["WEBHOOK_INTERNAL_TOKEN"]}
    with patch("leash_shared.lithic.update_card_state", return_value={}) as provider:
      self.assertEqual(
        self.client.post(
          "/internal/lithic/card-state",
          headers=headers,
          json={"card_token": "ins_1", "state": "OPEN"},
        ).status_code,
        422,
      )
      provider.assert_not_called()
      self.assertEqual(
        self.client.post(
          "/internal/lithic/card-state",
          headers=headers,
          json={"card_token": "ins_1", "state": "PAUSED"},
        ).status_code,
        502,
      )
    with patch(
      "leash_shared.lithic.update_card_state", return_value={"state": "PAUSED", "token": "ins_1"}
    ):
      self.assertEqual(
        self.client.post(
          "/internal/lithic/card-state", headers=headers, json={"card_token": "ins_1"}
        ).json()["state"],
        "PAUSED",
      )

  def test_simulation_is_blocked_before_operation_layer_and_enrollment_needs_https(self):
    headers = {"Authorization": "Bearer " + os.environ["WEBHOOK_INTERNAL_TOKEN"]}
    with patch("leash_shared.lithic.simulate_authorization") as provider:
      response = self.client.post(
        "/internal/lithic/simulate",
        headers=headers,
        json={
          "card_token": "ins_1",
          "amount_cents": 2999,
          "descriptor": "VOLT SUPPLY CO",
          "mcc": "5732",
        },
      )
      self.assertEqual(response.status_code, 503)
      provider.assert_not_called()
    with (
      patch.dict(os.environ, {"LITHIC_ASA_RESPONDER_URL": "http://public/rail/lithic/asa"}),
      patch("leash_shared.lithic.enroll_asa_responder") as provider,
    ):
      self.assertEqual(
        self.client.post(
          "/internal/lithic/asa/enroll",
          headers=headers,
          json={"url": "http://public/rail/lithic/asa"},
        ).status_code,
        422,
      )
      provider.assert_not_called()

  def test_merchant_cannot_seed_grants_or_kill_switch(self):
    headers = {"Authorization": "Bearer " + os.environ["WEBHOOK_CHARGE_TOKEN"]}
    self.assertEqual(self.client.put("/internal/grants", headers=headers, json={}).status_code, 401)
    self.assertEqual(
      self.client.post(
        "/internal/killswitch", headers=headers, json={"user_id": "usr_test", "on": True}
      ).status_code,
      401,
    )

  def test_api_control_token_cannot_authorize_charge(self):
    self.assertEqual(
      self.client.post(
        "/local/authorize",
        headers={"Authorization": "Bearer " + os.environ["WEBHOOK_INTERNAL_TOKEN"]},
        json={},
      ).status_code,
      401,
    )

  def test_incomplete_grant_rejected(self):
    self.assertEqual(
      self.client.put(
        "/internal/grants",
        headers={"Authorization": "Bearer " + os.environ["WEBHOOK_INTERNAL_TOKEN"]},
        json={"grant_id": "grt_fake"},
      ).status_code,
      422,
    )

  def test_http_grant_installation_enforces_short_lifetime(self):
    now = datetime.now(timezone.utc)
    body = {
      "grant_id": "grt_long",
      "payment_id": "pay_long",
      "mandate_id": "mnd_long",
      "mandate_version": 1,
      "mandate_hash": "a" * 64,
      "user_id": "usr_long",
      "verification_id": "ver_long",
      "verified_checkout_id": "chk_long",
      "verified_checkout_hash": "b" * 64,
      "payment_instrument_id": "ins_long",
      "merchant_id": "volt_supply_co",
      "merchant_descriptor": "VOLT SUPPLY CO",
      "mcc": "5732",
      "authorized_amount_cents": 2999,
      "currency": "USD",
      "merchant_binding_id": "bind_long",
      "bound_at": now.isoformat(),
      "issued_at": now.isoformat(),
      "expires_at": (now + timedelta(minutes=31)).isoformat(),
      "mandate_expires_at": (now + timedelta(hours=1)).isoformat(),
      "checkout_expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    response = self.client.put(
      "/internal/grants",
      headers={"Authorization": "Bearer " + os.environ["WEBHOOK_INTERNAL_TOKEN"]},
      json=body,
    )
    self.assertEqual(response.status_code, 422, response.text)
    self.assertIsNone(rail_main._store.get_grant("grt_long"))

  def test_authorization_rejects_caller_clock_and_lax_money(self):
    body = {
      "event_id": "evt_test",
      "instrument_token": "ins_test",
      "descriptor": "VOLT SUPPLY CO",
      "mcc": "5732",
      "amount_cents": 2999,
      "currency": "USD",
      "checkout_id": "chk_test",
      "checkout_hash": "a" * 64,
      "merchant_binding_id": "bind_test",
    }
    headers = {"Authorization": "Bearer " + os.environ["WEBHOOK_CHARGE_TOKEN"]}
    for change in [
      {"now": "2020-01-01T00:00:00Z"},
      {"amount_cents": True},
      {"amount_cents": 2999.0},
      {"mcc": 5732},
    ]:
      self.assertEqual(
        self.client.post("/local/authorize", headers=headers, json={**body, **change}).status_code,
        422,
      )
