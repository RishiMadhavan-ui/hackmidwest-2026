"""Payment critical path: store fetch + verify + grant seed + bind; fail closed."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402

from authority_errors import AuthorityError  # noqa: E402
from leash_shared.models import PaymentProposal, PurchaseMandate, canonical_json  # noqa: E402
from payment_service import request_payment  # noqa: E402
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


class _FakeConn:
  """Minimal conn for payment_attempts persistence + instrument lookup."""

  def __init__(self) -> None:
    self.rows: dict[str, dict] = {}
    self.events: list = []
    self._prior: dict | None = None

  def execute(self, sql: str, params=None):
    text = " ".join(sql.split())
    cur = MagicMock()
    if "FROM payment_attempts" in text and "COUNT" in text:
      cur.fetchone.return_value = {"n": 0}
    elif "FROM payment_attempts" in text and "ORDER BY created_at" in text:
      cur.fetchone.return_value = self._prior
    elif "FROM leash_users" in text or "FROM lithic_cards" in text:
      cur.fetchone.return_value = None
    elif "FROM agent_runs" in text:
      cur.fetchone.return_value = {"id": "run_payment_test"}
    elif "FROM mandate_confirmations" in text:
      cur.fetchone.return_value = {"verify_key": "unused"}
    elif "INSERT INTO payment_attempts" in text:
      self.rows[params[0]] = {
        "id": params[0],
        "status": params[7],
        "record": params[13],
      }
      cur.fetchone.return_value = None
    else:
      cur.fetchone.return_value = None
    return cur


class PaymentServiceTests(unittest.TestCase):
  def setUp(self) -> None:
    self.user_id = "usr_" + "a" * 32
    self.agent_id = "agt_" + "b" * 32
    self.principal = Principal(role="agent", user_id=self.user_id, agent_id=self.agent_id)
    self.mandate = _mandate(user_id=self.user_id, agent_id=self.agent_id)
    self.conn = _FakeConn()
    self.env = {
      "STORE_URL": "http://store.test",
      "STORE_API_TOKEN": "s" * 32,
      "WEBHOOK_URL": "http://rail.test",
      "WEBHOOK_INTERNAL_TOKEN": "w" * 32,
    }

  def _run(self, checkout_id: str, store_body: dict, *, seed_ok=True, bind_ok=True):
    proposal = PaymentProposal(mandate_id=self.mandate.id, checkout_id=checkout_id, run_id="run_payment_test")
    with (
      patch.dict("os.environ", self.env, clear=False),
      patch("payment_service.utc_now", return_value=NOW),
      patch("payment_service.current_mandate", return_value=self.mandate),
      patch("payment_service._confirmation_valid", return_value=True),
      patch("payment_service._fetch_store_checkout", return_value=store_body) as fetch,
      patch("payment_service._seed_grant") as seed,
      patch("payment_service._bind_store") as bind,
      patch("payment_service.append_event"),
    ):
      if not seed_ok:
        seed.side_effect = AuthorityError(502, "Payment rail rejected grant install")
      if not bind_ok:
        bind.side_effect = AuthorityError(502, "Trusted merchant rejected checkout binding")
      response = request_payment(self.conn, proposal, self.principal)
      return response, fetch, seed, bind

  def test_verified_charger_stays_blocked_until_durable_financial_controls(self) -> None:
    response, fetch, seed, bind = self._run("ckt_charger", _store_checkout())
    self.assertEqual(response.status, "blocked")
    self.assertIsNone(response.grant_id)
    self.assertIsNotNone(response.verification_id)
    self.assertEqual(response.reasons, ("financial_authority_unavailable",))
    fetch.assert_called_once_with("ckt_charger")
    seed.assert_not_called()
    bind.assert_not_called()
    self.assertIn(response.id, self.conn.rows)

  def test_blocks_subscription_same_merchant_amount_without_grant(self) -> None:
    response, _fetch, seed, bind = self._run("ckt_sub", _store_checkout(subscription=True))
    self.assertEqual(response.status, "blocked")
    self.assertIsNone(response.grant_id)
    self.assertTrue(response.reasons)
    seed.assert_not_called()
    bind.assert_not_called()

  def test_idempotent_replay_returns_prior_record_without_refetch(self) -> None:
    first, fetch, seed, bind = self._run("ckt_charger", _store_checkout())
    self.conn._prior = {
      "id": first.id,
      "record": first.model_dump(mode="json"),
    }
    proposal = PaymentProposal(mandate_id=self.mandate.id, checkout_id="ckt_charger", run_id="run_payment_test")
    with (
      patch.dict("os.environ", self.env, clear=False),
      patch("payment_service.utc_now", return_value=NOW),
      patch("payment_service.current_mandate", return_value=self.mandate),
      patch("payment_service._fetch_store_checkout") as fetch2,
      patch("payment_service._seed_grant") as seed2,
      patch("payment_service._bind_store") as bind2,
    ):
      second = request_payment(self.conn, proposal, self.principal)
    self.assertEqual(second.id, first.id)
    self.assertEqual(second.status, "blocked")
    fetch2.assert_not_called()
    seed2.assert_not_called()
    bind2.assert_not_called()
    self.assertEqual(fetch.call_count, 1)
    self.assertEqual(seed.call_count, 0)
    self.assertEqual(bind.call_count, 0)

  def test_missing_store_config_fails_closed(self) -> None:
    proposal = PaymentProposal(mandate_id=self.mandate.id, checkout_id="ckt_x", run_id="run_payment_test")
    with (
      patch.dict("os.environ", {"STORE_URL": "", "STORE_API_TOKEN": ""}, clear=False),
      patch("payment_service.current_mandate", return_value=self.mandate),
    ):
      with self.assertRaises(AuthorityError) as ctx:
        request_payment(self.conn, proposal, self.principal)
    self.assertEqual(ctx.exception.status, 503)

  def test_agent_cannot_mint_without_store_fetch(self) -> None:
    """Proposal cart/SKU is ignored; a store miss never becomes an approved grant."""
    proposal = PaymentProposal(
      mandate_id=self.mandate.id,
      checkout_id="ckt_missing",
      run_id="run_payment_test",
      proposal={
        "merchant_name": "spoofed merchant",
        "total_cents": 2999,
        "items": [
          {
            "name": "spoofed charger",
            "sku": "CHG-65W",
            "quantity": 1,
            "unit_cents": 2999,
          }
        ],
      },
    )
    with (
      patch.dict("os.environ", self.env, clear=False),
      patch("payment_service.utc_now", return_value=NOW),
      patch("payment_service.current_mandate", return_value=self.mandate),
      patch(
        "payment_service._fetch_store_checkout",
        side_effect=AuthorityError(404, "Checkout not found at trusted merchant"),
      ),
      patch("payment_service._seed_grant") as seed,
      patch("payment_service._bind_store") as bind,
    ):
      with self.assertRaises(AuthorityError) as ctx:
        request_payment(self.conn, proposal, self.principal)
    self.assertEqual(ctx.exception.status, 404)
    seed.assert_not_called()
    bind.assert_not_called()

  def test_invalid_trusted_facts_fail_closed_without_side_effects(self) -> None:
    changes = [
      ("currency", "EUR"), ("total_cents", "2999"), ("facts_hash", "0" * 64),
      ("recurring", "false"), ("status", "completed"), ("checkout_id", "ckt_other"),
    ]
    for field, value in changes:
      with self.subTest(field=field):
        store = _store_checkout()
        store[field] = value
        with self.assertRaises(AuthorityError) as error:
          self._run("ckt_charger", store)
        self.assertEqual(error.exception.status, 502)
    for field, value in [("quantity", 0), ("quantity", "1"), ("subscription", "false")]:
      with self.subTest(item_field=field):
        store = _store_checkout()
        store["line_items"][0][field] = value
        with self.assertRaises(AuthorityError) as error:
          self._run("ckt_charger", store)
        self.assertEqual(error.exception.status, 502)
    for field in ("recurring", "merchant_descriptor", "mcc", "facts_hash"):
      store = _store_checkout()
      del store[field]
      with self.subTest(missing=field), self.assertRaises(AuthorityError) as error:
        self._run("ckt_charger", store)
      self.assertEqual(error.exception.status, 502)

  def test_historical_grant_is_not_reissued_as_payment_authority(self) -> None:
    self.conn._prior = {"record": {"id": "pay_historical", "status": "approved", "reasons": [],
                                  "verification_id": "ver_historical", "grant_id": "grt_historical"}}
    with self.assertRaises(AuthorityError) as error:
      self._run("ckt_charger", _store_checkout())
    self.assertEqual(error.exception.status, 409)

  def test_unregistered_payment_request_cannot_fetch_or_seed(self) -> None:
    proposal = PaymentProposal(mandate_id=self.mandate.id, checkout_id="ckt_charger")
    with patch("payment_service._fetch_store_checkout") as fetch:
      with self.assertRaises(AuthorityError) as error:
        request_payment(self.conn, proposal, self.principal)
      self.assertEqual(error.exception.status, 422)
      fetch.assert_not_called()


if __name__ == "__main__":
  unittest.main()
