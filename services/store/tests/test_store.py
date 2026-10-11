"""Store service tests — catalog truth, attack containment, no PAN logging."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, reset_checkouts
from pages import render_product_page


class StoreTests(unittest.TestCase):
  def setUp(self) -> None:
    reset_checkouts()
    self.token = "isolated-store-credential-" + "a" * 32
    self.auth = patch.dict("os.environ", {"STORE_API_TOKEN": self.token})
    self.auth.start()
    self.addCleanup(self.auth.stop)
    self.client = TestClient(app, headers={"Authorization": "Bearer " + self.token})
    self.addCleanup(self.client.close)

  def test_healthz(self) -> None:
    r = self.client.get("/healthz")
    self.assertEqual(r.status_code, 200)
    self.assertEqual(r.json()["service"], "leash-store")

  def test_charger_page_clean_has_no_injection(self) -> None:
    with patch.dict("os.environ", {"STORE_EVIL_MODE": "0"}, clear=False):
      r = self.client.get("/products/chg-65w")
    self.assertEqual(r.status_code, 200)
    self.assertIn("text/html", r.headers["content-type"])
    body = r.text
    self.assertIn("65W USB-C GaN Laptop Charger", body)
    self.assertIn("Simulated merchant", body)
    self.assertIn("Start checkout", body)
    self.assertIn('action="./chg-65w/checkout"', body)
    self.assertNotIn("fulfillmentNote", body)
    self.assertNotIn("application/ld+json", body)

  def test_storefront_start_checkout_without_bearer(self) -> None:
    r = self.client.post("/products/chg-65w/checkout")
    self.assertEqual(r.status_code, 200)
    self.assertIn("text/html", r.headers["content-type"])
    self.assertIn("Checkout started", r.text)
    self.assertRegex(r.text, r"ckt_[0-9a-f]{16}")
    self.assertIn("chg-65w", r.text)

  def test_lab_001_003_unauthenticated_direct_attack_selection_denied(self) -> None:
    with TestClient(app) as visitor:
      for selector in ("1", "true", "yes", "on", "", "0&evil=1", "1&evil=0"):
        with self.subTest(selector=selector):
          r = visitor.get(f"/products/chg-65w?evil={selector}")
          self.assertEqual(r.status_code, 403)
          self.assertEqual(r.json()["detail"], "Attack Lab execution is disabled")

  def test_lab_002_store_service_credential_is_not_operator_authority(self) -> None:
    r = self.client.get("/products/chg-65w?evil=1")
    self.assertEqual(r.status_code, 403)

  def test_lab_004_environment_flags_cannot_enable_runtime_attack(self) -> None:
    with patch.dict("os.environ", {
      "STORE_EVIL_MODE": "1", "ATTACK_LAB_ENABLED": "1", "NEXT_PUBLIC_ATTACK_LAB": "1",
    }, clear=False), TestClient(app) as visitor:
      self.assertEqual(visitor.get("/products/chg-65w?evil=1").status_code, 403)
      for suffix in ("", "?evil=0", "?evil=false", "?evil=off", "?evil=no"):
        with self.subTest(suffix=suffix):
          r = visitor.get("/products/chg-65w" + suffix)
          self.assertEqual(r.status_code, 200)
          self.assertNotIn("fulfillmentNote", r.text)
          self.assertEqual(r.headers["cache-control"], "no-store")
      health = visitor.get("/health").json()
      self.assertFalse(health["evil_mode_env"])
      self.assertEqual(health["attack_lab_execution"], "disabled_pending_operator_authorization")

  def test_poisoned_offline_fixture_remains_available(self) -> None:
    html = render_product_page("chg-65w", evil=True)
    self.assertIn("application/ld+json", html)
    self.assertIn("voltcare", html)
    self.assertIn("fulfillmentNote", html)

  def test_checkout_truth_from_catalog_not_caller_name(self) -> None:
    r = self.client.post(
      "/api/checkouts",
      json={"sku": "SUB-CARE-MO", "quantity": 1},
    )
    self.assertEqual(r.status_code, 200)
    data = r.json()
    self.assertTrue(data["checkout_id"].startswith("ckt_"))
    self.assertEqual(data["total_cents"], 2999)
    self.assertTrue(data["recurring"])
    self.assertEqual(data["line_items"][0]["product_id"], "voltcare")
    self.assertEqual(data["line_items"][0]["category"], "protection_plan")
    self.assertEqual(data["mcc"], "5732")

  def test_checkout_accepts_product_id(self) -> None:
    r = self.client.post(
      "/api/checkouts",
      json={"product_id": "chg-65w", "quantity": 1},
    )
    self.assertEqual(r.status_code, 200)
    data = r.json()
    self.assertFalse(data["recurring"])
    self.assertEqual(data["line_items"][0]["product_id"], "chg-65w")

  def test_get_checkout_for_verifier(self) -> None:
    created = self.client.post("/api/checkouts", json={"sku": "CHG-65W"}).json()
    r = self.client.get(f"/api/checkouts/{created['checkout_id']}")
    self.assertEqual(r.status_code, 200)
    self.assertEqual(r.json()["checkout_id"], created["checkout_id"])
    self.assertEqual(r.json()["total_cents"], 2999)

  def test_complete_without_bind_fails_closed(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    r = self.client.post(
      f"/api/checkouts/{created['checkout_id']}/complete",
      json={
        "payment_id": "pay_1",
        "card_token": "ins_local_demo",
        "card": {"number": "4111111111111111", "exp_month": 12, "exp_year": 2030, "cvv": "123"},
      },
    )
    self.assertEqual(r.status_code, 403)
    self.assertIn("not bound", r.json()["detail"])

  def _bind(
    self,
    cid: str,
    *,
    payment_id: str = "pay_" + "1" * 32,
    instrument: str = "ins_local_demo",
    amount: int = 2999,
    checkout_hash: str | None = None,
  ) -> dict:
    from datetime import datetime, timedelta, timezone

    body = {
      "payment_id": payment_id,
      "grant_id": "grt_" + "a" * 32,
      "instrument_token": instrument,
      "merchant_binding_id": f"bind_{cid}",
      "checkout_hash": checkout_hash or ("c" * 64),
      "authorized_amount_cents": amount,
      "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10))
      .isoformat()
      .replace("+00:00", "Z"),
    }
    r = self.client.post(f"/api/checkouts/{cid}/bind", json=body)
    self.assertEqual(r.status_code, 200, r.text)
    return body

  def test_bind_rejects_amount_mismatch(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    from datetime import datetime, timedelta, timezone

    r = self.client.post(
      f"/api/checkouts/{created['checkout_id']}/bind",
      json={
        "payment_id": "pay_" + "1" * 32,
        "grant_id": "grt_" + "a" * 32,
        "instrument_token": "ins_local_demo",
        "merchant_binding_id": "bind_x",
        "checkout_hash": "d" * 64,
        "authorized_amount_cents": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10))
        .isoformat()
        .replace("+00:00", "Z"),
      },
    )
    self.assertEqual(r.status_code, 409)

  def test_bound_checkout_cannot_charge_without_durable_controls(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    cid = created["checkout_id"]
    binding = self._bind(cid)
    with patch.dict("os.environ", {"WEBHOOK_URL": "http://rail.test", "WEBHOOK_CHARGE_TOKEN": "c" * 32}):
      with patch("httpx.Client") as client_cls:
        result = self.client.post(
          f"/api/checkouts/{cid}/complete",
          json={"payment_id": binding["payment_id"], "instrument_token": binding["instrument_token"]},
        )
        self.assertEqual(result.status_code, 503, result.text)
        self.assertIn("durable payment reconciliation", result.json()["detail"])
        client_cls.assert_not_called()
    observed = self.client.get(f"/api/checkouts/{cid}").json()
    self.assertEqual(observed["status"], "open")
    self.assertIsNone(observed["rail"])

  def test_complete_wrong_instrument_declines_without_rail(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    cid = created["checkout_id"]
    binding = self._bind(cid)
    with patch.dict(
      "os.environ",
      {"WEBHOOK_URL": "http://rail.test", "WEBHOOK_CHARGE_TOKEN": "c" * 32},
      clear=False,
    ):
      with patch("httpx.Client") as client_cls:
        post = client_cls.return_value.__enter__.return_value.post
        r = self.client.post(
          f"/api/checkouts/{cid}/complete",
          json={"payment_id": binding["payment_id"], "instrument_token": "ins_wrong"},
        )
        self.assertEqual(r.status_code, 409)
        post.assert_not_called()
    self.assertEqual(self.client.get(f"/api/checkouts/{cid}").json()["status"], "open")

  def test_complete_cannot_call_lithic_or_mark_a_checkout_paid(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    cid = created["checkout_id"]
    binding = self._bind(cid)

    class _LogCapture(logging.Handler):
      def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

      def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))

    class _Resp:
      status_code = 200
      content = b'{"result":"APPROVED"}'

      def json(self):
        return {"result": "APPROVED"}

    capture = _LogCapture()
    logger = logging.getLogger("leash.store")
    logger.addHandler(capture)
    try:
      with patch.dict(
        "os.environ",
        {"WEBHOOK_URL": "http://rail.test", "WEBHOOK_CHARGE_TOKEN": "c" * 32},
        clear=False,
      ):
        with patch("httpx.Client") as client_cls:
          client_cls.return_value.__enter__.return_value.post.return_value = _Resp()
          r = self.client.post(
            f"/api/checkouts/{cid}/complete",
            json={
              "payment_id": binding["payment_id"],
              "instrument_token": binding["instrument_token"],
              "card": {
                "number": "4111111111111111",
                "exp_month": 12,
                "exp_year": 2030,
                "cvv": "042",
              },
            },
          )
      self.assertEqual(r.status_code, 503, r.text)
      joined = "\n".join(capture.messages)
      self.assertNotIn("4111111111111111", joined)
      self.assertNotIn("042", joined)
    finally:
      logger.removeHandler(capture)

  def test_store_api_token_when_configured(self) -> None:
    with patch.dict("os.environ", {"STORE_API_TOKEN": self.token}, clear=False):
      # Reload auth reads env at request time — no reload needed.
      denied = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}, headers={"Authorization": ""})
      self.assertEqual(denied.status_code, 401)
      ok = self.client.post(
        "/api/checkouts",
        json={"product_id": "chg-65w"},
        headers={"Authorization": "Bearer " + self.token},
      )
      self.assertEqual(ok.status_code, 200)

  def test_missing_or_short_configuration_fails_closed_and_not_ready(self) -> None:
    for value in ("", "short"):
      with patch.dict("os.environ", {"STORE_API_TOKEN": value}):
        self.assertEqual(self.client.post("/api/checkouts", json={"sku": "CHG-65W"}).status_code, 503)
        self.assertEqual(self.client.get("/readyz").status_code, 503)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

  def test_checkout_read_and_completion_require_auth(self) -> None:
    cid = self.client.post("/api/checkouts", json={"sku": "CHG-65W"}).json()["checkout_id"]
    with patch("httpx.Client") as client_cls:
      self.assertEqual(self.client.get(f"/api/checkouts/{cid}", headers={"Authorization": "Bearer invalid"}).status_code, 401)
      self.assertEqual(self.client.post(f"/api/checkouts/{cid}/complete", json={"payment_id": "claimed"}, headers={"Authorization": ""}).status_code, 401)
      client_cls.return_value.__enter__.return_value.post.assert_not_called()

  def test_same_merchant_price_currency_keeps_actual_sku_constraints(self) -> None:
    charger = self.client.post("/api/checkouts", json={"sku": "CHG-65W"}).json()
    attack = self.client.post("/api/checkouts", json={"sku": "SUB-CARE-MO"}).json()
    for field in ("merchant_descriptor", "mcc", "total_cents", "currency"):
      self.assertEqual(charger[field], attack[field])
    self.assertEqual(charger["total_cents"], 2999)
    self.assertIsNone(charger["rail"])
    self.assertEqual(charger["line_items"][0]["sku"], "CHG-65W")
    self.assertEqual(charger["line_items"][0]["category"], "laptop_charger")
    self.assertFalse(charger["line_items"][0]["subscription"])
    self.assertIn({"name": "connector", "value": "USB-C"}, charger["line_items"][0]["attributes"])
    self.assertEqual(attack["line_items"][0]["sku"], "SUB-CARE-MO")
    self.assertTrue(attack["line_items"][0]["subscription"])
    self.assertEqual(attack["line_items"][0]["billing_interval"], "monthly")

  def test_conflicting_product_aliases_and_invalid_quantities_rejected(self) -> None:
    self.assertEqual(self.client.post("/api/checkouts", json={"sku": "CHG-65W", "product_id": "voltcare"}).status_code, 422)
    for quantity in (True, "1", 1.5, 0, 100):
      self.assertEqual(self.client.post("/api/checkouts", json={"sku": "CHG-65W", "quantity": quantity}).status_code, 422)

  def test_validation_error_does_not_echo_sensitive_card_input(self) -> None:
    cid = self.client.post("/api/checkouts", json={"sku": "CHG-65W"}).json()["checkout_id"]
    response = self.client.post(f"/api/checkouts/{cid}/complete", json={"payment_id": "claimed", "card": {"exp_month": "4111111111111111", "cvv": "987"}})
    self.assertEqual(response.status_code, 422)
    self.assertEqual(response.json(), {"detail": "Invalid store request"})

  def test_catalog_attributes_cannot_be_changed_through_returned_copy(self) -> None:
    from catalog import get_product
    product = get_product("CHG-65W")
    product["attributes"][0]["value"] = "barrel"
    self.assertEqual(get_product("CHG-65W")["attributes"][0]["value"], "USB-C")


if __name__ == "__main__":
  unittest.main()
