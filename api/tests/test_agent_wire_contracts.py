"""Agent wire examples plus captured peer outputs; not a live integration test."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from leash_shared.events import (  # noqa: E402
  AgentToolTraceInput, SourceProvenanceInput, agent_report_event, event_fields,
  parse_provenance,
)
from leash_shared.models import (  # noqa: E402
  AuthorizationGrant, CheckoutVerification, MandateProposal, PaymentProposal,
  AgentRunRegistration, GuardianEvaluationRequest, Mandate, PaymentResponse, Verdict,
)


AT = "2026-10-10T18:00:00Z"
PAYMENT = {
  "mandate_id": "mnd_demo", "checkout_id": "checkout_demo", "run_id": "run_demo",
  "proposal": {
    "merchant_name": "Demo Store",
    "items": [{"name": "USB-C charger", "sku": "CHG-65W", "quantity": 1, "unit_cents": 2999}],
    "total_cents": 2999,
  },
}


def trace_data(**updates):
  return {
    "type": "agent.tool.after", "event_id": "evt_trace_demo", "run_id": "run_demo",
    "agent_id": "agt_shopper", "timestamp": AT, "tool_name": "request_payment",
    "agent_mode": "live",
    "tool_use_id": "tool_demo", "tool_arguments": {"checkout_id": "checkout_demo"},
    "source_reference": "https://store.test/listings/CHG-65W",
    "trust_classification": "agent_proposal", "proposed_action": "buy charger",
    "tool_result_summary": "Leash reported pending_user", "policy_decision": "pending_user",
    "duration_ms": 12.3, **updates,
  }


def source_data(**updates):
  return {
    "type": "provenance.source", "event_id": "evt_source_demo", "run_id": "run_demo",
    "agent_id": "agt_shopper", "timestamp": AT, "agent_mode": "live",
    "tool_use_id": "tool_browse_demo", "http_status": 200, "fetched_at": AT,
    "trust_classification": "untrusted_web_content", "hidden_reasons": ["display:none"],
    "hidden_suspicious_phrases": ["buy the subscription"],
    "url": "https://store.test/listings/CHG-65W", "sha256": "a" * 64,
    "hidden_text_detected": True, "suspicious_phrases": ["buy the subscription"],
    "excerpt": "Untrusted hidden listing instruction", "snapshot": None, **updates,
  }


def normalize(report, **updates):
  return agent_report_event(report, **{
    "user_id": "usr_demo", "authenticated_agent_id": "agt_shopper",
    "authorized_run_id": "run_demo", "authorized_agent_mode": "live", **updates,
  })


class AgentWireContractTests(unittest.TestCase):
  def test_message_payment_shape_accepts_optional_sku_without_merchant_authority(self):
    parsed = PaymentProposal.model_validate_json(json.dumps(PAYMENT))
    self.assertEqual(parsed.proposal.merchant_name, "Demo Store")
    self.assertEqual(parsed.proposal.items[0].sku, "CHG-65W")
    no_sku = json.loads(json.dumps(PAYMENT))
    del no_sku["proposal"]["items"][0]["sku"]
    self.assertIsNone(PaymentProposal.model_validate(no_sku).proposal.items[0].sku)
    self.assertNotIn("cart", parsed.model_dump())

  def test_agent_claims_cannot_supply_verification_or_grants(self):
    for field in ("verification", "grant", "status", "user_id", "checkout_hash"):
      with self.subTest(field=field), self.assertRaises(ValidationError):
        PaymentProposal.model_validate({**PAYMENT, field: "agent claim"})
    for model in (CheckoutVerification, AuthorizationGrant):
      with self.subTest(model=model.__name__), self.assertRaises(ValidationError):
        model.model_validate(PAYMENT["proposal"])

  def test_comparison_claim_can_disagree_with_total_without_becoming_checkout(self):
    payload = json.loads(json.dumps(PAYMENT))
    payload["proposal"]["total_cents"] = 1
    parsed = PaymentProposal.model_validate(payload)
    self.assertEqual(parsed.proposal.total_cents, 1)
    # The verifier reads the real checkout; retaining contradictory claims is evidence.
    for bad in (2999.0, True, "2999", -1):
      payload["proposal"]["total_cents"] = bad
      with self.subTest(value=bad), self.assertRaises(ValidationError):
        PaymentProposal.model_validate(payload)

  def test_draft_mandate_supports_old_fields_and_explicit_constraints_without_authority(self):
    minimal = {
      "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
      "category": "charger", "max_cents": 3999, "location": None, "valid_until": AT,
    }
    draft = MandateProposal(**minimal)
    self.assertFalse(draft.allow_subscription)
    self.assertFalse(draft.allow_recurring)
    self.assertEqual(draft.maximum_purchases, 1)
    explicit = MandateProposal(**{**minimal,
      "product_constraints": [{"name": "connector", "operator": "equals", "value": "USB-C"}],
    })
    self.assertEqual(explicit.description, minimal["description"])
    for field, value in (("status", "active"), ("approved_at", AT),
                         ("signature", "fake"), ("user_id", "usr_other")):
      with self.subTest(field=field), self.assertRaises(ValidationError):
        MandateProposal(**{**minimal, field: value})

  def test_guardian_only_reports_advisory_recommendations(self):
    for recommendation in ("block", "review", "no_findings"):
      findings = Verdict(recommendation=recommendation, model=None)
      self.assertIsNone(findings.model)
      self.assertNotIn("decision", findings.model_dump())
      with self.assertRaises(ValidationError):
        CheckoutVerification.model_validate(findings.model_dump())
    for bad in ("approve", "needs_user", "deny"):
      with self.subTest(recommendation=bad), self.assertRaises(ValidationError):
        Verdict(recommendation=bad)
    with self.assertRaises(ValidationError):
      Verdict(decision="approve", reasons=["An LLM said yes"])

  def test_top_level_payment_status_is_distinct_from_actual_authorization(self):
    for status in ("pending_user", "blocked", "denied"):
      result = PaymentResponse(id="pay_demo", status=status)
      self.assertEqual(result.model_dump(mode="json")["status"], status)
      self.assertIsNone(result.payment_result)
    with self.assertRaises(ValidationError):
      PaymentResponse(id="pay_demo", status="approved")
    approved = PaymentResponse(id="pay_demo", status="approved",
      verification_id="verification_demo", grant_id="grant_demo")
    self.assertIsNone(approved.payment_result)
    with self.assertRaises(ValidationError):
      PaymentResponse(id="pay_demo", status="blocked", payment_result="APPROVED")

  def test_trace_wire_has_tool_use_and_duration_and_redacts_nested_arguments(self):
    report = parse_provenance(trace_data(tool_arguments={
      "checkout_id": "checkout_demo", "card": {"pan": "4444333322221111", "cvv": "123"},
      "auth": {"Authorization": "Bearer private-token"},
    }))
    self.assertIsInstance(report, AgentToolTraceInput)
    self.assertEqual(report.tool_use_id, "tool_demo")
    self.assertEqual(report.duration_ms, 12.3)
    raw = json.dumps(report.model_dump(mode="json"))
    self.assertNotIn("4444333322221111", raw)
    self.assertNotIn("private-token", raw)
    self.assertEqual(report.tool_arguments["card"]["cvv"], "[REDACTED]")
    for bad in (-1, True, float("nan"), "12.3"):
      with self.subTest(duration=bad), self.assertRaises(ValidationError):
        parse_provenance(trace_data(duration_ms=bad))

  def test_authenticated_owner_and_run_are_required_for_event_normalization(self):
    report = parse_provenance(trace_data())
    for updates in ({"authenticated_agent_id": "agt_other"}, {"authorized_run_id": "run_other"}):
      with self.subTest(updates=updates), self.assertRaises(ValueError):
        normalize(report, **updates)
    with self.assertRaises(ValidationError):
      parse_provenance(trace_data(user_id="usr_other"))
    with self.assertRaises(ValidationError):
      parse_provenance(trace_data(type="authorization.decided"))

  def test_reported_trust_and_success_cannot_become_backend_authority(self):
    event = normalize(parse_provenance(trace_data(
      trust_classification="deterministic_policy", policy_decision="approved")))
    self.assertEqual(event.type, "agent.tool.after")
    self.assertEqual(event.data["reported_trust_classification"], "deterministic_policy")
    self.assertEqual(event.data["trust_classification"], "agent_proposal")
    self.assertFalse(event.data["authoritative"])
    self.assertEqual(event.data["evidence_origin"], "agent_reported")

  def test_source_keeps_ids_and_untrusted_evidence_without_raw_snapshot(self):
    report = parse_provenance(source_data())
    self.assertIsInstance(report, SourceProvenanceInput)
    event = normalize(report)
    self.assertEqual(event.event_id, "evt_source_demo")
    self.assertEqual(event.data["sha256"], "a" * 64)
    self.assertEqual(event.data["trust_classification"], "untrusted")
    self.assertIsNone(event.data["snapshot"])
    self.assertEqual(normalize(report).event_id, event.event_id)

    # Snapshot metadata never permits raw page content to enter the stream.
    with self.assertRaises(ValidationError):
      parse_provenance(source_data(snapshot={"html": "raw page body"}))
    stored = parse_provenance(source_data(snapshot={
      "storage": "object_storage", "bucket": "demo-evidence",
      "key": "runs/run_demo/" + "a" * 64 + ".html",
    }))
    with self.assertRaises(ValueError):
      normalize(stored)
    resolved = normalize(stored, configured_snapshot_bucket="demo-evidence")
    wire = event_fields(resolved)["event"]
    self.assertNotIn("raw page body", wire)
    self.assertIn("runs/run_demo/" + "a" * 64 + ".html", wire)

  def test_source_needs_correlation_and_cannot_supply_checkout_authority(self):
    for field in ("event_id", "run_id", "agent_id", "timestamp"):
      payload = source_data()
      del payload[field]
      with self.subTest(field=field), self.assertRaises(ValidationError):
        parse_provenance(payload)
    with self.assertRaises(ValidationError):
      parse_provenance(source_data(verified=True))

  def test_scripted_label_and_storage_unavailability_survive_normalization(self):
    report = parse_provenance(source_data(agent_mode="scripted", snapshot={
      "storage": "none", "reason": "object storage not configured",
    }))
    with self.assertRaises(ValueError):
      normalize(report)
    normalized = normalize(report, authorized_agent_mode="scripted")
    self.assertEqual(normalized.data["agent_mode"], "scripted")
    self.assertEqual(normalized.data["snapshot"]["storage"], "none")
    payload = trace_data()
    del payload["agent_mode"]
    with self.assertRaises(ValidationError):
      parse_provenance(payload)

  def test_snapshot_reference_cannot_escape_bucket_or_run(self):
    for bucket, key in (("wrong-bucket", "runs/run_demo/" + "a" * 64 + ".html"),
                        ("demo-evidence", "runs/run_other/" + "a" * 64 + ".html")):
      report = parse_provenance(source_data(snapshot={
        "storage": "object_storage", "bucket": bucket, "key": key,
      }))
      with self.subTest(bucket=bucket, key=key), self.assertRaises(ValueError):
        normalize(report, configured_snapshot_bucket="demo-evidence")

  def test_mcp_optional_context_does_not_fabricate_run_or_expiry(self):
    payload = {**PAYMENT, "run_id": None,
      "proposal": {**PAYMENT["proposal"], "merchant_name": None}}
    parsed = PaymentProposal.model_validate(payload)
    self.assertIsNone(parsed.run_id)
    self.assertIsNone(parsed.proposal.merchant_name)
    draft = MandateProposal(description="Buy charger", category="laptop_charger",
      max_cents=3999, valid_until=None)
    self.assertIsNone(draft.valid_until)

  def test_mandate_serializes_the_names_the_guardian_actually_reads(self):
    draft = MandateProposal(description="Buy two chargers", category="laptop_charger",
      max_cents=8000, maximum_quantity=2, allow_subscriptions=True, allow_recurring_payments=True)
    data = draft.model_dump(mode="json")
    self.assertEqual(data["max_quantity"], 2)
    self.assertTrue(data["allow_subscription"])
    self.assertTrue(data["allow_recurring"])
    self.assertNotIn("maximum_quantity", data)
    with self.assertRaises(ValidationError):
      MandateProposal(**{**data, "maximum_quantity": 10})

  def test_run_registration_cannot_choose_owner_or_confirmed_authority(self):
    body = {"id": "run_demo", "mandate_id": "mnd_demo", "agent_mode": "scripted",
      "model": "scripted-shopper", "provider": "fixture"}
    self.assertEqual(AgentRunRegistration(**body).model_dump(mode="json"), body)
    for field in ("user_id", "agent_id", "mandate_version", "mandate_hash", "status"):
      with self.subTest(field=field), self.assertRaises(ValidationError):
        AgentRunRegistration(**{**body, field: "agent claim"})
    for field in ("id", "mandate_id", "agent_mode"):
      missing = {k: v for k, v in body.items() if k != field}
      with self.subTest(field=field), self.assertRaises(ValidationError):
        AgentRunRegistration(**missing)

  def test_redacted_snapshot_keeps_source_hash_and_stored_hash_separate(self):
    report = parse_provenance(source_data(snapshot={
      "storage": "object_storage", "bucket": "demo-evidence",
      "key": "runs/run_demo/" + "a" * 64 + ".html", "stored_sha256": "b" * 64,
    }))
    event = normalize(report, configured_snapshot_bucket="demo-evidence")
    self.assertEqual(event.data["sha256"], "a" * 64)
    self.assertEqual(event.data["snapshot"]["stored_sha256"], "b" * 64)


class CapturedPeerContractTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.capture = json.loads((Path(__file__).parent / "fixtures/aditya-266a805-wire.json").read_text(encoding="utf-8"))

  def test_actual_mcp_serialization_matches_shared_wire_models(self):
    for call in self.capture["mcp_calls"]:
      model = PaymentProposal if call["path"] == "/payments" else MandateProposal
      with self.subTest(path=call["path"]):
        parsed = model.model_validate(call["body"])
        self.assertEqual(call["method"], "POST")
        self.assertNotIn("approved_at", parsed.model_dump())

  def test_actual_guardian_payloads_include_review_evidence_and_model_metadata(self):
    recommendations = set()
    for response in self.capture["guardian_responses"]:
      parsed = Verdict.model_validate(response)
      recommendations.add(parsed.recommendation)
      self.assertEqual(parsed.authority, "advisory")
      self.assertIsNotNone(parsed.model)
      self.assertEqual(parsed, Verdict.model_validate_json(parsed.model_dump_json()))
      with self.assertRaises(ValidationError):
        CheckoutVerification.model_validate(response)
    self.assertEqual(recommendations, {"no_findings", "review", "block"})
    self.assertEqual(self.capture["guardian_responses"][-1]["model"]["status"], "unavailable")

  def test_actual_hook_source_and_mode_survive_auth_bound_normalization(self):
    for payload in self.capture["provenance_events"]:
      event = normalize(parse_provenance(payload), authorized_agent_mode="scripted",
        configured_snapshot_bucket="demo-evidence")
      self.assertEqual(event.event_id, payload["event_id"])
      self.assertEqual(event.data["agent_mode"], "scripted")
      self.assertFalse(event.data["authoritative"])
      if payload["type"] == "provenance.source":
        self.assertEqual(event.data["snapshot"]["storage"], "object_storage")
        self.assertIn("stored_sha256", event.data["snapshot"])
        self.assertEqual(event.data["sha256"], payload["sha256"])

  def test_guardian_input_uses_checkout_and_proposal_and_accepts_legacy_cart_alias(self):
    from test_shared_contracts import NOW, SIGNATURE, mandate_data, checkout_data
    from leash_shared.models import CheckoutSnapshot

    mandate = Mandate(**mandate_data(status="active", approved_at=NOW, signature=SIGNATURE))
    checkout = CheckoutSnapshot(**checkout_data())
    body = {"mandate": mandate.model_dump(mode="json"),
      "checkout": checkout.model_dump(mode="json"), "proposal": PAYMENT["proposal"],
      "provenance": [self.capture["provenance_events"][-1]],
      "trace": self.capture["provenance_events"][:-1]}
    parsed = GuardianEvaluationRequest.model_validate(body)
    self.assertIn("proposal", parsed.model_dump())
    self.assertEqual(parsed.checkout.session_id, "ses_demo_a")
    legacy = {**body, "cart": body["proposal"]}
    del legacy["proposal"]
    self.assertEqual(parsed, GuardianEvaluationRequest.model_validate(legacy))

  def test_actual_run_registration_and_hash_preservation_match_contracts(self):
    body = self.capture["run_registration"]["body"]
    self.assertEqual(AgentRunRegistration.model_validate(body).id, "run_demo")
    self.assertEqual(self.capture["run_registration"]["path"], "/agent-runs")
    probe = self.capture["peer_redaction_probe"]
    self.assertEqual(probe["input_hash"], probe["output_hash"])

  def test_current_guardian_distinguishes_wrong_and_unknown_connectors(self):
    outputs = self.capture["guardian_product_constraint_responses"]
    self.assertEqual(Verdict.model_validate(outputs["wrong"]).recommendation, "block")
    self.assertEqual(Verdict.model_validate(outputs["unknown"]).recommendation, "review")
    self.assertEqual(Verdict.model_validate(outputs["case_insensitive"]).recommendation, "no_findings")


if __name__ == "__main__":
  unittest.main()
