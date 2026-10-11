"""Pure domain tests; confirmation/merchant authentication are explicitly fixtures."""

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402
from checkout_verifier import verify_checkout  # noqa: E402
from leash_shared.models import (
  CheckoutSnapshot,
  PurchaseMandate,
  REQUIRED_VERIFICATION_CHECKS,
)  # noqa: E402
from pydantic import ValidationError  # noqa: E402


class CheckoutVerifierTests(unittest.TestCase):
  def setUp(self):
    self.now = datetime.now(timezone.utc)
    self.mandate = {
      "id": "mnd_test",
      "user_id": "usr_test",
      "agent_id": "agt_test",
      "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
      "category": "laptop_charger",
      "max_cents": 3999,
      "valid_from": self.now - timedelta(minutes=1),
      "valid_until": self.now + timedelta(minutes=20),
      "created_at": self.now - timedelta(minutes=1),
      "approved_at": self.now - timedelta(seconds=30),
      "signature": base64.b64encode(bytes(64)).decode(),
      "status": "active",
      "product_constraints": [
        {"name": "connector", "value": "USB-C"},
        {"name": "wattage", "operator": "minimum", "value": 65},
      ],
    }
    self.checkout = {
      "checkout_id": "chk_charger",
      "revision": 1,
      "purchase_attempt_id": "pay_test",
      "user_id": "usr_test",
      "merchant_id": "volt_supply_co",
      "session_id": "session_test",
      "merchant": {
        "name": "Volt Supply Co.",
        "descriptor": "VOLT SUPPLY CO",
        "mcc": "5732",
        "url": "https://store.example",
      },
      "items": [
        {
          "sku": "CHG-65W",
          "product_name": "USB-C charger",
          "product_category": "laptop_charger",
          "quantity": 1,
          "unit_cents": 2999,
          "recurring": False,
          "subscription": False,
          "attributes": [
            {"name": "connector", "value": "usb-c"},
            {"name": "wattage", "value": 65},
          ],
        }
      ],
      "subtotal_cents": 2999,
      "tax_cents": 0,
      "shipping_cents": 0,
      "total_cents": 2999,
      "expires_at": self.now + timedelta(minutes=10),
      "source": {
        "source_id": "trusted-store",
        "url": "https://store.example/api/checkouts/chk_charger",
        "retrieved_at": self.now - timedelta(seconds=1),
        "method": "server_fetch",
      },
    }

  def verify(self, *, mandate=None, checkout=None, **kwargs):
    return verify_checkout(
      PurchaseMandate.model_validate(mandate or self.mandate),
      CheckoutSnapshot.model_validate(checkout or self.checkout),
      now=self.now,
      **{
        "confirmation_valid": True,
        "checkout_authenticated": True,
        "successful_purchases": 0,
        **kwargs,
      },
    )

  def test_charger_passes_all_fifteen_checks(self):
    record = self.verify()
    self.assertEqual(record.decision, "VERIFIED")
    self.assertEqual(
      {check.name for check in record.checks}, REQUIRED_VERIFICATION_CHECKS
    )

  def test_same_merchant_amount_currency_subscription_blocked(self):
    item = {
      **self.checkout["items"][0],
      "sku": "SUB-CARE-MO",
      "product_category": "subscription",
      "recurring": True,
      "subscription": True,
      "billing_interval": "monthly",
    }
    record = self.verify(
      checkout={
        **self.checkout,
        "items": [item],
        "checkout_id": "chk_subscription",
      }
    )
    self.assertEqual(record.decision, "BLOCKED")
    self.assertTrue(
      {
        "category_mismatch",
        "subscription_prohibited",
        "recurring_prohibited",
      }.issubset(record.reasons)
    )

  def test_total_includes_all_charges_and_exclusive_under_40_boundary(self):
    for total in (3999, 4000, 4138):
      record = self.verify(
        checkout={
          **self.checkout,
          "tax_cents": total - 2999,
          "total_cents": total,
        }
      )
      self.assertEqual(record.decision, "VERIFIED" if total == 3999 else "BLOCKED")

  def test_unknown_duplicate_and_wrong_attributes_fail_closed(self):
    for attributes in (
      [],
      [{"name": "connector", "value": "barrel"}],
      self.checkout["items"][0]["attributes"]
      + [{"name": "connector", "value": "barrel"}],
    ):
      item = {**self.checkout["items"][0], "attributes": attributes}
      self.assertEqual(
        self.verify(checkout={**self.checkout, "items": [item]}).decision,
        "BLOCKED",
      )

  def test_confirmation_evidence_and_scope_cannot_be_inferred(self):
    for kwargs in (
      {"confirmation_valid": False},
      {"checkout_authenticated": False},
      {"successful_purchases": 1},
    ):
      self.assertEqual(self.verify(**kwargs).decision, "BLOCKED")
    for kwargs in ({"confirmation_valid": "true"}, {"successful_purchases": False}):
      with self.assertRaises(ValueError):
        self.verify(**kwargs)

  def test_checkout_owner_expiry_and_future_evidence(self):
    for changes in (
      {"user_id": "usr_other"},
      {"expires_at": self.now},
      {
        "source": {
          **self.checkout["source"],
          "retrieved_at": self.now + timedelta(seconds=1),
        }
      },
    ):
      self.assertEqual(
        self.verify(checkout={**self.checkout, **changes}).decision, "BLOCKED"
      )

  def test_unknown_category_merchant_and_shipping_never_waived(self):
    for changes in (
      {"category": "space_heater"},
      {"merchant_allowlist": ["other_merchant"]},
      {"location": "Kansas City"},
      {"shipping_constraints": {"postal_code": "64101"}},
    ):
      self.assertEqual(
        self.verify(mandate={**self.mandate, **changes}).decision, "BLOCKED"
      )

  def test_matrix_quantity_shipping_tax_and_wrong_category(self):
    cases = [
      ("CHK-004", {"quantity":2,"unit_cents":1499}, 0, 0, "quantity_exceeded"),
      ("CHK-005", {"unit_cents":3600}, 0, 600, "amount_over_limit"),
      ("CHK-006", {"unit_cents":3900}, 200, 0, "amount_over_limit"),
      ("CHK-009", {"product_category":"headphones"}, 0, 0, "category_mismatch"),
      ("CHK-018", {"unit_cents":0}, 0, 0, "checkout_price_nonpositive"),
    ]
    for case_id,changes,tax,shipping,reason in cases:
      item={**self.checkout["items"][0],**changes}
      subtotal=item["quantity"]*item["unit_cents"]
      with self.subTest(case=case_id):
        record=self.verify(checkout={**self.checkout,"items":[item],"subtotal_cents":subtotal,
          "tax_cents":tax,"shipping_cents":shipping,"total_cents":subtotal+tax+shipping})
        self.assertEqual(record.decision,"BLOCKED")
        self.assertIn(reason,record.reasons)

  def test_matrix_currency_arithmetic_quantity_and_negative_price_validation(self):
    cases = [("CHK-007",{"currency":"EUR"}),
             ("CHK-011",{"subtotal_cents":2998}), ("CHK-012",{"total_cents":2998})]
    for field,value in (("quantity",0),("quantity",-1),("unit_cents",-1)):
      cases.append(("CHK-018",{"items":[{**self.checkout["items"][0],field:value}]}))
    for case_id,changes in cases:
      with self.subTest(case=case_id), self.assertRaises(ValidationError):
        self.verify(checkout={**self.checkout,**changes})
