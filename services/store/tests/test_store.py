"""Store service tests — catalog truth, evil toggle, no PAN logging."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, reset_checkouts


class StoreTests(unittest.TestCase):
  def setUp(self) -> None:
    reset_checkouts()
    self.client = TestClient(app)

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
    self.assertNotIn("fulfillmentNote", body)
    self.assertNotIn("application/ld+json", body)

  def test_charger_page_evil_query_injects_json_ld(self) -> None:
    with patch.dict("os.environ", {"STORE_EVIL_MODE": "0"}, clear=False):
      r = self.client.get("/products/chg-65w?evil=1")
    self.assertEqual(r.status_code, 200)
    self.assertIn("application/ld+json", r.text)
    self.assertIn("voltcare", r.text)
    self.assertIn("fulfillmentNote", r.text)

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

  def test_complete_requires_card_token(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    r = self.client.post(
      f"/api/checkouts/{created['checkout_id']}/complete",
      json={
        "payment_id": "pay_1",
        "card": {"number": "4111111111111111", "exp_month": 12, "exp_year": 2030, "cvv": "123"},
      },
    )
    self.assertEqual(r.status_code, 422)
    self.assertIn("card_token", r.json()["detail"])

  def test_complete_calls_lithic_simulate_without_logging_pan(self) -> None:
    created = self.client.post("/api/checkouts", json={"product_id": "chg-65w"}).json()
    cid = created["checkout_id"]

    class _LogCapture(logging.Handler):
      def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

      def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))

    capture = _LogCapture()
    logger = logging.getLogger("leash.store")
    logger.addHandler(capture)
    try:
      with patch("leash_shared.lithic.simulate_authorization") as sim:
        sim.return_value = {"token": "txn_demo", "debugging_assertion": "ok"}
        r = self.client.post(
          f"/api/checkouts/{cid}/complete",
          json={
            "payment_id": "pay_1",
            "card_token": "card_tok_demo",
            "card": {
              "number": "4111111111111111",
              "exp_month": 12,
              "exp_year": 2030,
              "cvv": "042",
            },
          },
        )
      self.assertEqual(r.status_code, 200, r.text)
      self.assertEqual(r.json()["status"], "completed")
      sim.assert_called_once()
      kwargs = sim.call_args.kwargs
      self.assertEqual(kwargs["card_token"], "card_tok_demo")
      self.assertEqual(kwargs["amount_cents"], 2999)
      self.assertEqual(kwargs["descriptor"], "VOLT SUPPLY CO")
      self.assertEqual(kwargs["mcc"], "5732")
      joined = "\n".join(capture.messages)
      self.assertNotIn("4111111111111111", joined)
      self.assertNotIn("042", joined)
      self.assertNotIn("card_tok_demo", joined)
    finally:
      logger.removeHandler(capture)

  def test_store_api_token_when_configured(self) -> None:
    with patch.dict("os.environ", {"STORE_API_TOKEN": "secret-store"}, clear=False):
      # Reload auth reads env at request time — no reload needed.
      denied = self.client.post("/api/checkouts", json={"product_id": "chg-65w"})
      self.assertEqual(denied.status_code, 401)
      ok = self.client.post(
        "/api/checkouts",
        json={"product_id": "chg-65w"},
        headers={"Authorization": "Bearer secret-store"},
      )
      self.assertEqual(ok.status_code, 200)


if __name__ == "__main__":
  unittest.main()
