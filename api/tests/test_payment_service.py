"""Trusted merchant connector unit tests; durable workflow tests use real PostgreSQL."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402

from authority_errors import AuthorityError  # noqa: E402
from leash_shared.models import PaymentProposal, PurchaseMandate, canonical_json  # noqa: E402
from payment_service import request_payment, _map_checkout, _fetch_store_checkout, _require_integrations  # noqa: E402
from principals import Principal  # noqa: E402


NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


def _mandate(**overrides) -> PurchaseMandate:
  base = {
    "id": "mnd_charger",
    "user_id": "usr_" + "a" * 32,
    "agent_id": "agt_" + "b" * 32,
    "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
    "category": "laptop_charger",
    "max_cents": 3999,
    "valid_from": NOW - timedelta(minutes=1),
    "valid_until": NOW + timedelta(minutes=20),
    "created_at": NOW - timedelta(minutes=1),
    "approved_at": NOW - timedelta(seconds=30),
    "signature": base64.b64encode(bytes(64)).decode(),
    "status": "active",
    "product_constraints": [
      {"name": "connector", "operator": "equals", "value": "USB-C"},
      {"name": "wattage", "operator": "minimum", "value": 65},
    ],
  }
  base.update(overrides)
  return PurchaseMandate.model_validate(base)


def _store_checkout(*, sku: str = "CHG-65W", subscription: bool = False) -> dict:
  record = _raw_store_checkout(sku=sku, subscription=subscription)
  record["facts_hash"] = hashlib.sha256(canonical_json({key: record[key] for key in (
    "checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents"
  )}).encode("utf-8")).hexdigest()
  return record


def _raw_store_checkout(*, sku: str = "CHG-65W", subscription: bool = False) -> dict:
  if subscription:
    return {
      "checkout_id": "ckt_sub",
      "line_items": [
        {
          "product_id": "voltcare",
          "sku": "SUB-CARE-MO",
          "name": "VoltCare Protection Plan",
          "price_cents": 2999,
          "quantity": 1,
          "recurring": True,
          "category": "protection_plan",
          "subscription": True,
          "billing_interval": "monthly",
          "attributes": [],
        }
      ],
      "total_cents": 2999,
      "recurring": True,
      "currency": "USD",
      "merchant_descriptor": "VOLT SUPPLY CO",
      "mcc": "5732",
      "status": "open",
      "facts_hash": "a" * 64,
    }
  return {
    "checkout_id": "ckt_charger",
    "line_items": [
      {
        "product_id": "chg-65w",
        "sku": sku,
        "name": "65W USB-C GaN Laptop Charger",
        "price_cents": 2999,
        "quantity": 1,
        "recurring": False,
        "category": "laptop_charger",
        "subscription": False,
        "billing_interval": None,
        "attributes": [
          {"name": "connector", "value": "USB-C"},
          {"name": "wattage", "value": 65},
        ],
      }
    ],
    "total_cents": 2999,
    "recurring": False,
    "currency": "USD",
    "merchant_descriptor": "VOLT SUPPLY CO",
    "mcc": "5732",
    "status": "open",
    "facts_hash": "b" * 64,
  }


class PaymentServiceTests(unittest.TestCase):
  def setUp(self):
    self.env = {"STORE_URL": "http://store.test", "STORE_API_TOKEN": "s" * 32}
    self.principal = Principal("agent", "usr_" + "a" * 32, "agt_" + "b" * 32)

  def mapped(self, store):
    with patch.dict("os.environ", self.env):
      return _map_checkout(store, user_id=self.principal.user_id, payment_id="pay_test", now=NOW)

  def test_connector_preserves_itemized_canonical_facts_as_observation(self):
    snapshot = self.mapped(_store_checkout())
    self.assertEqual(snapshot.total_cents, 2999)
    self.assertEqual(snapshot.items[0].sku, "CHG-65W")
    self.assertEqual(snapshot.items[0].attributes[0].value, "USB-C")
    self.assertEqual(snapshot.source.method, "server_fetch")

  def test_signature_attack_has_identical_merchant_amount_currency(self):
    charger = self.mapped(_store_checkout())
    subscription = self.mapped(_store_checkout(subscription=True))
    self.assertEqual((charger.merchant, charger.total_cents, charger.currency),
                     (subscription.merchant, subscription.total_cents, subscription.currency))
    self.assertTrue(subscription.items[0].recurring)
    self.assertTrue(subscription.items[0].subscription)

  def test_invalid_trusted_facts_fail_closed_without_side_effects(self):
    for field, value in [("currency", "EUR"), ("total_cents", "2999"), ("facts_hash", "0"*64),
                         ("recurring", "false"), ("status", "completed")]:
      with self.subTest(field=field):
        store = _store_checkout()
        store[field] = value
        with self.assertRaises(AuthorityError) as error:
          self.mapped(store)
        self.assertEqual(error.exception.status, 502)
    for field, value in [("quantity", 0), ("quantity", "1"), ("subscription", "false")]:
      store = _store_checkout()
      store["line_items"][0][field] = value
      with self.subTest(field=field), self.assertRaises(AuthorityError):
        self.mapped(store)
    for field in ("recurring", "merchant_descriptor", "mcc", "facts_hash"):
      store = _store_checkout()
      del store[field]
      with self.subTest(missing=field), self.assertRaises(AuthorityError):
        self.mapped(store)

  def test_missing_or_unsafe_config_fails_closed(self):
    for url in ("", "http://user:secret@store.test", "http://store.test?key=secret", "http://store.test/api", "file:///x"):
      with self.subTest(url=url), patch.dict("os.environ", {**self.env, "STORE_URL": url}):
        with self.assertRaises(AuthorityError) as error:
          _require_integrations()
        self.assertEqual(error.exception.status, 503)

  def test_checkout_identifier_cannot_select_another_path_or_origin(self):
    identifier = "ckt_x/../other?query=yes#fragment"
    response = Mock(is_success=True, status_code=200, json=lambda: {"checkout_id": identifier})
    with patch.dict("os.environ", self.env), patch("payment_service.httpx.Client") as client:
      client.return_value.__enter__.return_value.get.return_value = response
      _fetch_store_checkout(identifier)
      url = client.return_value.__enter__.return_value.get.call_args.args[0]
      self.assertEqual(url, "http://store.test/api/checkouts/ckt_x%2F..%2Fother%3Fquery%3Dyes%23fragment")
      self.assertFalse(client.call_args.kwargs["follow_redirects"])

  def test_merchant_errors_and_redirects_do_not_become_checkout_evidence(self):
    for code in (302, 404, 401, 500):
      with self.subTest(code=code), patch.dict("os.environ", self.env), patch("payment_service.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = Mock(status_code=code, is_success=False)
        with self.assertRaises(AuthorityError) as error:
          _fetch_store_checkout("ckt_test")
        self.assertEqual(error.exception.status, 404 if code == 404 else 502)

  def test_unregistered_payment_request_cannot_fetch_or_seed(self):
    proposal = PaymentProposal(mandate_id="mnd_charger", checkout_id="ckt_charger")
    with patch("payment_service._fetch_store_checkout") as fetch:
      with self.assertRaises(AuthorityError) as error:
        request_payment(None, proposal, self.principal)
      self.assertEqual(error.exception.status, 422)
      fetch.assert_not_called()

  def test_human_cannot_invoke_sensitive_payment_tool(self):
    with self.assertRaises(AuthorityError) as error:
      request_payment(None, PaymentProposal(mandate_id="mnd_charger", checkout_id="ckt_charger"),
                      Principal("human", self.principal.user_id))
    self.assertEqual(error.exception.status, 403)


if __name__ == "__main__":
  unittest.main()
