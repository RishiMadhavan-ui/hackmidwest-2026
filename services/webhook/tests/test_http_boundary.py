import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


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
