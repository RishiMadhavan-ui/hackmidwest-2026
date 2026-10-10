"""Security contract tests run without Redis, Lithic, inference or pytest."""

from __future__ import annotations

import base64
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError


# Cameron owns packaging; exercise namespace imports from the agreed source root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from leash_shared.events import (  # noqa: E402
  AuditEvent, EventType, event_fields, publish, sanitize_event_data,
)
from leash_shared.models import (  # noqa: E402
  REQUIRED_VERIFICATION_CHECKS,
  AgentRun,
  AgentTraceEvent,
  AgentPurchaseProposal,
  AuthorizationAttempt,
  AuthorizationDecision,
  AuthorizationGrant,
  CanonicalProduct,
  Cart,
  CartProposal,
  CheckoutSnapshot,
  CheckoutVerification,
  Mandate,
  MandateProposal,
  PaymentDecision,
  PaymentProposal,
  PaymentRequest,
  PaymentResponse,
  PreApproval,
  ProductConstraint,
  ProductListing,
  ProvenanceEvent,
  PurchaseMandate,
  SecurityIncident,
  Verdict,
  canonical_json,
  cart_hash,
  checkout_hash,
  mandate_hash,
  payload_hash,
)


NOW = datetime(2026, 10, 10, 18, tzinfo=timezone.utc)
SIGNATURE = base64.b64encode(bytes(64)).decode("ascii")
MERCHANT = {
  "name": "Demo Store", "descriptor": "LEASH DEMO STORE",
  "mcc": "5732", "url": "https://store.test",
}
ITEM = {"name": "USB-C charger", "quantity": 1, "unit_cents": 2999}


def mandate_data(**updates):
  return {
    "id": "mnd_demo", "user_id": "usr_demo", "agent_id": "agt_shopper",
    "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
    "category": "charger", "max_cents": 3999,
    "product_constraints": [{"name": "connector", "value": "USB-C"}],
    "merchant_allowlist": ["merchant_demo"], "created_at": NOW,
    "valid_from": NOW, "valid_until": NOW + timedelta(hours=1),
    **updates,
  }


def cart_data(**updates):
  return {
    "id": "crt_demo", "mandate_id": "mnd_demo", "merchant": MERCHANT,
    "items": [ITEM], "total_cents": 2999, **updates,
  }


def checkout_data(**updates):
  return {
    "checkout_id": "checkout_demo", "revision": 1,
    "purchase_attempt_id": "pay_demo", "user_id": "usr_demo",
    "session_id": "ses_demo_a",
    "merchant_id": "merchant_demo", "merchant": MERCHANT,
    "items": [{
      "sku": "CHG-65W", "product_name": "USB-C charger",
      "product_category": "charger", "quantity": 1, "unit_cents": 2999,
      "subscription": False, "recurring": False,
      "attributes": [{"name": "connector", "value": "USB-C"}],
    }],
    "subtotal_cents": 2999, "tax_cents": 0, "shipping_cents": 0,
    "total_cents": 2999, "expires_at": NOW + timedelta(minutes=20),
    "source": {
      "source_id": "configured_demo_store", "url": "https://store.test/internal",
      "retrieved_at": NOW, "method": "server_fetch",
    },
    **updates,
  }


def verification_data(**updates):
  mandate = Mandate(**mandate_data())
  checkout = CheckoutSnapshot(**checkout_data())
  return {
    "id": "verification_demo", "user_id": "usr_demo",
    "purchase_attempt_id": "pay_demo", "mandate_id": mandate.id,
    "mandate_version": mandate.version, "mandate_hash": mandate_hash(mandate),
    "checkout_id": checkout.checkout_id, "checkout_hash": checkout_hash(checkout),
    "decision": "VERIFIED", "verified_at": NOW,
    "checks": [{"name": name, "passed": True, "detail": "Verified by backend"}
               for name in sorted(REQUIRED_VERIFICATION_CHECKS)],
    **updates,
  }


def grant_data(**updates):
  mandate = Mandate(**mandate_data())
  checkout = CheckoutSnapshot(**checkout_data())
  return {
    "grant_id": "grant_demo", "payment_id": "pay_demo",
    "mandate_id": mandate.id, "mandate_version": mandate.version,
    "mandate_hash": mandate_hash(mandate), "user_id": mandate.user_id,
    "verification_id": "verification_demo",
    "verified_checkout_id": checkout.checkout_id,
    "verified_checkout_hash": checkout_hash(checkout),
    "payment_instrument_id": "instrument_demo", "merchant_id": "merchant_demo",
    "merchant_descriptor": MERCHANT["descriptor"], "mcc": MERCHANT["mcc"],
    "authorized_amount_cents": 2999, "merchant_binding_id": "binding_demo",
    "bound_at": NOW, "issued_at": NOW, "expires_at": NOW + timedelta(minutes=10),
    "mandate_expires_at": mandate.valid_until,
    "checkout_expires_at": checkout.expires_at,
    **updates,
  }


class MoneyAndShapeTests(unittest.TestCase):
  def test_money_rejects_float_bool_string_and_negative(self):
    for bad in (29.99, 2999.0, True, False, "2999", -1):
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        Mandate(**mandate_data(max_cents=bad))
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        AuthorizationGrant(**grant_data(authorized_amount_cents=bad))

  def test_currency_and_mcc_are_unambiguous(self):
    with self.assertRaises(ValidationError):
      Mandate(**mandate_data(currency="EUR"))
    for bad in (5732, "732", "hotel"):
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        Cart(**cart_data(merchant={**MERCHANT, "mcc": bad}))

  def test_quantities_and_booleans_are_strict(self):
    for bad in (0, -1, 1.0, True, "1"):
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        Mandate(**mandate_data(maximum_quantity=bad))
    for bad in ("false", 0, None):
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        Mandate(**mandate_data(allow_subscriptions=bad))

  def test_unknown_fields_and_secrets_are_not_contract_fields(self):
    for name in ("pan", "cvv", "secret", "authorized_by_agent"):
      with self.subTest(field=name), self.assertRaises(ValidationError):
        AuthorizationGrant(**grant_data(**{name: "forbidden"}))

  def test_id_and_timestamp_validation(self):
    with self.assertRaises(ValidationError):
      Mandate(**mandate_data(user_id="agt_wrong_role"))
    for bad in (NOW.replace(tzinfo=None), "2026-10-10T18:00:00", 1791655200, "1791655200"):
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        Mandate(**mandate_data(created_at=bad))

  def test_checkout_missing_facts_and_totals_fail(self):
    for field in ("product_category", "subscription", "recurring", "sku"):
      data = checkout_data()
      del data["items"][0][field]
      with self.subTest(field=field), self.assertRaises(ValidationError):
        CheckoutSnapshot(**data)
    for field in ("subtotal_cents", "total_cents"):
      with self.subTest(field=field), self.assertRaises(ValidationError):
        CheckoutSnapshot(**checkout_data(**{field: 2998}))
    with self.assertRaises(ValidationError):
      CheckoutSnapshot(**checkout_data(expires_at=NOW))

  def test_unknown_category_is_explicit_evidence_not_verification(self):
    data = checkout_data()
    data["items"][0]["product_category"] = None
    checkout = CheckoutSnapshot(**data)
    self.assertIsNone(checkout.items[0].product_category)

  def test_payment_proposal_requires_checkout_reference(self):
    with self.assertRaises(ValidationError):
      PaymentProposal(mandate_id="mnd_demo", run_id="run_demo", proposal=AgentPurchaseProposal(
        merchant_name="Demo Store", items=[ITEM], total_cents=2999,
      ))

  def test_constraint_operators_require_unambiguous_values(self):
    for operator, bad in (("minimum", True), ("maximum", "10"),
                          ("contains", 10), ("contains", " ")):
      with self.subTest(operator=operator, value=bad), self.assertRaises(ValidationError):
        ProductConstraint(name="wattage", operator=operator, value=bad)
    self.assertEqual(ProductConstraint(name="wattage", operator="minimum", value=65).value, 65)


class HashAndMandateTests(unittest.TestCase):
  def test_canonical_encoding_and_known_sha256_vector(self):
    self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')
    self.assertEqual(canonical_json({"text": "é"}), '{"text":"\\u00e9"}')
    self.assertEqual(payload_hash({}),
      "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a")
    for bad in (float("nan"), float("inf"), float("-inf")):
      with self.subTest(value=bad), self.assertRaises(ValueError):
        canonical_json({"value": bad})

  def test_utc_equivalence_and_json_round_trip(self):
    shifted = NOW.astimezone(timezone(timedelta(hours=-5)))
    first = Mandate(**mandate_data())
    second = Mandate(**mandate_data(created_at=shifted, valid_from=shifted))
    self.assertEqual(first.canonical_payload_hash, second.canonical_payload_hash)
    self.assertEqual(first, Mandate.model_validate_json(first.model_dump_json()))
    self.assertEqual(canonical_json({"at": shifted}), '{"at":"2026-10-10T18:00:00Z"}')

  def test_legacy_proposal_hash_vector_and_id_exclusion(self):
    expected = "cfaa7470b730c2b4e76b5a3f80552d117b157c49a96819c020a642c5fda4557f"
    cart = Cart(**cart_data())
    self.assertEqual(cart.cart_hash, expected)
    self.assertEqual(cart_hash(cart_data(id="crt_other")), expected)
    self.assertEqual(cart_hash(cart.model_dump(mode="json")), expected)
    with self.assertRaises(ValidationError):
      Cart(**cart_data(cart_hash="0" * 64))
    with self.assertRaises(ValidationError):
      cart_hash({**cart_data(), "currency": "EUR"})

  def test_each_semantic_authority_change_changes_hash(self):
    original = Mandate(**mandate_data()).canonical_payload_hash
    mutations = {
      "description": "Buy a subscription", "category": "subscription",
      "max_cents": 4000, "maximum_quantity": 2, "maximum_purchases": 2,
      "allow_subscriptions": True, "allow_recurring_payments": True,
      "merchant_allowlist": ["other_merchant"], "version": 2,
      "valid_until": NOW + timedelta(hours=2),
      "product_constraints": [{"name": "connector", "value": "USB-A"}],
      "shipping_constraints": {"country": "US", "max_shipping_cents": 100},
    }
    for field, value in mutations.items():
      with self.subTest(field=field):
        self.assertNotEqual(Mandate(**mandate_data(**{field: value})).canonical_payload_hash, original)

  def test_hash_is_bound_and_confirmation_is_not_inferred(self):
    draft = Mandate(**mandate_data())
    self.assertEqual(draft.status, "proposed")
    self.assertIsNone(draft.approved_at)
    with self.assertRaises(ValidationError):
      Mandate(**mandate_data(status="active"))
    active = Mandate(**mandate_data(
      status="active", approved_at=NOW, signature=SIGNATURE,
      canonical_payload_hash=draft.canonical_payload_hash,
    ))
    self.assertEqual(active.canonical_payload_hash, draft.canonical_payload_hash)
    revoked = Mandate(**{**active.model_dump(), "status": "revoked"})
    self.assertEqual(revoked.canonical_payload_hash, draft.canonical_payload_hash)
    with self.assertRaises(ValidationError):
      Mandate(**{**active.model_dump(), "max_cents": 5000})
    with self.assertRaises(ValidationError):
      Mandate(**mandate_data(status="active", approved_at=NOW, signature="0" * 64))

  def test_records_and_nested_authority_are_immutable(self):
    mandate = Mandate(**mandate_data())
    with self.assertRaises(ValidationError):
      mandate.max_cents = 5000
    with self.assertRaises(ValidationError):
      mandate.product_constraints[0].value = "subscription"
    self.assertIsInstance(mandate.merchant_allowlist, tuple)

  def test_checkout_hash_changes_for_same_price_subscription(self):
    charger = CheckoutSnapshot(**checkout_data())
    data = checkout_data()
    data["items"][0].update(
      sku="SUB-CARE-MO", product_name="Premium subscription",
      product_category="subscription", subscription=True, recurring=True,
    )
    subscription = CheckoutSnapshot(**data)
    self.assertEqual(charger.merchant, subscription.merchant)
    self.assertEqual(charger.total_cents, subscription.total_cents)
    self.assertNotEqual(charger.checkout_hash, subscription.checkout_hash)
    with self.assertRaises(ValidationError):
      CheckoutSnapshot(**{**data, "checkout_hash": charger.checkout_hash})

  def test_checkout_hash_binds_revision_session_source_and_fulfillment(self):
    original = CheckoutSnapshot(**checkout_data()).checkout_hash
    mutations = {
      "revision": 2, "user_id": "usr_other", "purchase_attempt_id": "pay_other",
      "expires_at": NOW + timedelta(minutes=19), "shipping_country": "US",
      "source": {**checkout_data()["source"], "source_id": "other_source"},
    }
    for field, value in mutations.items():
      with self.subTest(field=field):
        self.assertNotEqual(CheckoutSnapshot(**checkout_data(**{field: value})).checkout_hash, original)
    retrieved = {**checkout_data()["source"], "retrieved_at": NOW + timedelta(minutes=1)}
    self.assertEqual(CheckoutSnapshot(**checkout_data(source=retrieved)).checkout_hash, original)


class VerificationAndGrantTests(unittest.TestCase):
  def test_verified_requires_all_named_checks_and_no_failure(self):
    complete = verification_data()
    CheckoutVerification(**complete)
    with self.assertRaises(ValidationError):
      CheckoutVerification(**{**complete, "checks": complete["checks"][:-1]})
    failed = [*complete["checks"]]
    failed[0] = {**failed[0], "passed": False}
    with self.assertRaises(ValidationError):
      CheckoutVerification(**{**complete, "checks": failed})
    with self.assertRaises(ValidationError):
      CheckoutVerification(**{**complete, "checks": complete["checks"] + [complete["checks"][0]]})
    blocked = CheckoutVerification(**{**complete,
      "decision": "BLOCKED", "checks": failed, "reasons": ["Unauthorized subscription"],
    })
    self.assertEqual(blocked.decision, "BLOCKED")

  def test_guardian_recommendation_is_not_a_verification(self):
    verdict = Verdict(recommendation="no_findings", reasons=["No suspicious evidence found"])
    self.assertIsNone(verdict.model)
    with self.assertRaises(ValidationError):
      CheckoutVerification.model_validate(verdict.model_dump())

  def test_grant_cannot_outlive_authority_or_checkout(self):
    for expiry in (NOW, NOW + timedelta(minutes=21), NOW + timedelta(hours=2)):
      with self.subTest(expiry=expiry), self.assertRaises(ValidationError):
        AuthorizationGrant(**grant_data(expires_at=expiry))
    with self.assertRaises(ValidationError):
      AuthorizationGrant(**grant_data(bound_at=NOW + timedelta(seconds=1)))
    with self.assertRaises(ValidationError):
      AuthorizationGrant(**grant_data(merchant_binding_id=""))

  def test_preapproval_exactly_matches_grant(self):
    grant = AuthorizationGrant(**grant_data())
    preapproval = PreApproval.from_grant(grant, cart_hash=Cart(**cart_data()).cart_hash)
    self.assertEqual(preapproval.max_cents, 2999)
    self.assertEqual(preapproval.grant.verified_checkout_hash, checkout_hash(CheckoutSnapshot(**checkout_data())))
    for field, value in {"max_cents": 3000, "card_token": "other_instrument", "mandate_version": 2}.items():
      with self.subTest(field=field), self.assertRaises(ValidationError):
        PreApproval(**{**preapproval.model_dump(), field: value})

  def test_approved_payment_requires_evidence_chain_and_explicit_rail(self):
    decision = {
      "id": "decision_demo", "attempt_id": "attempt_demo", "rail": "local_simulator",
      "result": "APPROVED", "reason": "approved", "decision_source": "deterministic_policy",
      "latency_ms": 1.2, "decided_at": NOW,
    }
    with self.assertRaises(ValidationError):
      PaymentDecision(**decision)
    decision.update(payment_id="pay_demo", grant_id="grant_demo",
      verification_id="verification_demo", mandate_hash="a" * 64, checkout_hash="b" * 64)
    PaymentDecision(**decision)
    with self.assertRaises(ValidationError):
      PaymentDecision(**{**decision, "rail": "live"})
    with self.assertRaises(ValidationError):
      PaymentDecision(**{**decision, "latency_ms": float("nan")})
    for bad in (True, "1.2"):
      with self.subTest(latency=bad), self.assertRaises(ValidationError):
        PaymentDecision(**{**decision, "latency_ms": bad})

  def test_all_public_domain_schemas_are_generated_and_closed(self):
    models = (
      PurchaseMandate, MandateProposal, Cart, CartProposal, AgentPurchaseProposal,
      PaymentProposal, PaymentResponse, CanonicalProduct,
      ProductListing, CheckoutSnapshot, CheckoutVerification, Verdict,
      AuthorizationGrant, PreApproval, PaymentRequest, AuthorizationAttempt,
      PaymentDecision, AuthorizationDecision, AgentRun, AgentTraceEvent,
      ProvenanceEvent, SecurityIncident, AuditEvent,
    )
    for model in models:
      with self.subTest(model=model.__name__):
        self.assertIs(model.model_json_schema()["additionalProperties"], False)


class EventTests(unittest.IsolatedAsyncioTestCase):
  async def test_publish_wire_format_is_sanitized_and_failure_is_visible(self):
    class Client:
      async def xadd(self, name, fields):
        self.name, self.fields = name, fields
        return b"1791655200000-0"

    client = Client()
    event = AuditEvent(type="agent.step", user_id="usr_demo", at=NOW,
      data={"card_token": "instrument_demo", "card_last4": "1111",
            "card_number": "4444333322221111", "nested": {"cvv": "123"}})
    stream_id = await publish(client, event)
    self.assertEqual(stream_id, "1791655200000-0")
    self.assertEqual(client.name, "leash:events")
    restored = AuditEvent.model_validate_json(client.fields["event"])
    self.assertEqual(restored.event_id, event.event_id)
    self.assertEqual(restored.data["card_token"], "instrument_demo")
    self.assertNotIn("4444333322221111", client.fields["event"])
    self.assertEqual(restored.data["nested"]["cvv"], "[REDACTED]")

    class FailedClient:
      async def xadd(self, name, fields):
        raise OSError("state store unavailable")

    with self.assertRaises(OSError):
      await publish(FailedClient(), event)

  async def test_sensitive_attributes_and_free_text_are_redacted(self):
    safe = sanitize_event_data({
      "tool_arguments": [{"name": "CVV", "value": 123}],
      "source": "card 4444 3333 2222 1111; Bearer abc.def; cvv=123",
      "nested": [{"INFERENCE_API_KEY": "private-key"}],
    })
    self.assertEqual(safe["tool_arguments"][0]["value"], "[REDACTED]")
    self.assertNotIn("1111", safe["source"])
    self.assertNotIn("abc.def", safe["source"])
    self.assertNotIn("123", safe["source"])
    self.assertEqual(safe["nested"][0]["INFERENCE_API_KEY"], "[REDACTED]")

  async def test_mutable_data_is_resanitized_at_write_boundary(self):
    event = AuditEvent(type=EventType.AGENT_STEP, user_id="usr_demo", data={})
    event.data["cvv"] = "123"
    self.assertEqual(json.loads(event_fields(event)["event"])["data"]["cvv"], "[REDACTED]")

  async def test_invalid_events_are_not_publishable(self):
    for event_type, data in (("agent.claimed_paid", {}), ("agent.step", {"n": float("nan")})):
      with self.subTest(event_type=event_type), self.assertRaises(ValidationError):
        AuditEvent(type=event_type, user_id="usr_demo", data=data)

  async def test_redaction_preserves_hashes_and_instrument_identifiers(self):
    checkout_hash = "a" + "1234567890123456" + "b" * 47
    safe = sanitize_event_data({
      "checkout_hash": checkout_hash, "card_token": "card_1234567890123456",
      "source": "pan=4111-1111-1111-1111; card_number=4111111111111111",
      "OBJ_SECRET_ACCESS_KEY": "private-storage-key",
      "AGENT_TOKEN_OTHER": "private-agent-key",
    })
    self.assertEqual(safe["checkout_hash"], checkout_hash)
    self.assertEqual(safe["card_token"], "card_1234567890123456")
    self.assertNotIn("4111", safe["source"])
    self.assertEqual(safe["OBJ_SECRET_ACCESS_KEY"], "[REDACTED]")
    self.assertEqual(safe["AGENT_TOKEN_OTHER"], "[REDACTED]")

  async def test_empty_stream_id_is_not_reported_as_success(self):
    class Client:
      async def xadd(self, name, fields):
        return b""

    with self.assertRaises(ValueError):
      await publish(Client(), AuditEvent(type="agent.step", user_id="usr_demo", data={}))


if __name__ == "__main__":
  unittest.main()
