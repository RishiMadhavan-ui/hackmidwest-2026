"""Shared domain records; validation and hashing do not grant payment authority."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
  AfterValidator,
  AliasChoices,
  AwareDatetime,
  BaseModel,
  BeforeValidator,
  ConfigDict,
  Field,
  JsonValue,
  StrictBool,
  StrictInt,
  StrictStr,
  model_validator,
)


def _timestamp_input(value: Any) -> Any:
  # Numeric epoch values hide timezone mistakes in cross-service payloads.
  if not isinstance(value, (str, datetime)):
    raise ValueError("timestamps must be timezone-aware ISO 8601 or datetime values")
  if isinstance(value, str) and not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
    raise ValueError("timestamp strings must use ISO 8601 date and time")
  return value


def _utc(value: datetime) -> datetime:
  return value.astimezone(timezone.utc)


def _nonblank(value: str) -> str:
  if not value.strip():
    raise ValueError("text cannot be blank")
  return value


UtcDatetime = Annotated[
  AwareDatetime, BeforeValidator(_timestamp_input), AfterValidator(_utc)
]
Text = Annotated[StrictStr, Field(min_length=1), AfterValidator(_nonblank)]
Cents = Annotated[StrictInt, Field(ge=0)]
Quantity = Annotated[StrictInt, Field(ge=1)]
Version = Annotated[StrictInt, Field(ge=1)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Mcc = Annotated[StrictStr, Field(pattern=r"^[0-9]{4}$")]
Currency = Literal["USD"]
Scalar = StrictStr | StrictInt | StrictBool
UserId = Annotated[StrictStr, Field(pattern=r"^usr_[A-Za-z0-9_-]+$")]
AgentId = Annotated[StrictStr, Field(pattern=r"^agt_[A-Za-z0-9_-]+$")]
MandateId = Annotated[StrictStr, Field(pattern=r"^mnd_[A-Za-z0-9_-]+$")]
CartId = Annotated[StrictStr, Field(pattern=r"^crt_[A-Za-z0-9_-]+$")]
PaymentId = Annotated[StrictStr, Field(pattern=r"^pay_[A-Za-z0-9_-]+$")]
RunId = Annotated[StrictStr, Field(pattern=r"^run_[A-Za-z0-9_-]+$")]


def _signature(value: str) -> str:
  try:
    decoded = base64.b64decode(value, validate=True)
  except (ValueError, TypeError) as exc:
    raise ValueError("signature must be base64 Ed25519 signature bytes") from exc
  if len(decoded) != 64:
    raise ValueError("Ed25519 signatures contain 64 bytes")
  return value


Signature = Annotated[StrictStr, AfterValidator(_signature)]


class Contract(BaseModel):
  model_config = ConfigDict(
    extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True
  )


class MandateStatus(StrEnum):
  PROPOSED = "proposed"
  ACTIVE = "active"
  REVOKED = "revoked"
  EXPIRED = "expired"
  SUPERSEDED = "superseded"


class GuardianRecommendation(StrEnum):
  BLOCK = "block"
  REVIEW = "review"
  NO_FINDINGS = "no_findings"


class VerificationDecision(StrEnum):
  VERIFIED = "VERIFIED"
  BLOCKED = "BLOCKED"
  REQUIRES_REVIEW = "REQUIRES_REVIEW"


class GrantStatus(StrEnum):
  ISSUED = "ISSUED"
  CONSUMED = "CONSUMED"
  EXPIRED = "EXPIRED"
  REVOKED = "REVOKED"


class PaymentOutcome(StrEnum):
  APPROVED = "APPROVED"
  DECLINED = "DECLINED"
  ERROR = "ERROR"


class PaymentStatus(StrEnum):
  PENDING_GUARDIAN = "pending_guardian"
  PENDING_USER = "pending_user"
  APPROVED = "approved"
  DENIED = "denied"
  EXPIRED = "expired"
  USED = "used"


class PaymentRail(StrEnum):
  LOCAL_SIMULATOR = "local_simulator"
  LITHIC_SANDBOX = "lithic_sandbox"


class TrustClassification(StrEnum):
  UNTRUSTED = "untrusted"
  AGENT_PROPOSAL = "agent_proposal"
  TRUSTED_CHECKOUT = "trusted_checkout"
  DETERMINISTIC_POLICY = "deterministic_policy"


class RunStatus(StrEnum):
  PENDING = "pending"
  RUNNING = "running"
  COMPLETED = "completed"
  FAILED = "failed"


class ConstraintOperator(StrEnum):
  EQUALS = "equals"
  CONTAINS = "contains"
  MINIMUM = "minimum"
  MAXIMUM = "maximum"


class ProductAttribute(Contract):
  name: Text
  value: Scalar


class ProductConstraint(ProductAttribute):
  operator: ConstraintOperator = ConstraintOperator.EQUALS

  @model_validator(mode="after")
  def validate_operator(self) -> Self:
    if self.operator in {ConstraintOperator.MINIMUM, ConstraintOperator.MAXIMUM}:
      if type(self.value) is not int:
        raise ValueError("numeric bounds require an integer value")
    if self.operator == ConstraintOperator.CONTAINS:
      if not isinstance(self.value, str) or not self.value.strip():
        raise ValueError("contains requires a nonblank string value")
    return self


class ShippingConstraints(Contract):
  country: Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")] | None = None
  postal_code: Text | None = None
  deliver_by: UtcDatetime | None = None
  max_shipping_cents: Cents | None = None


class MandateProposal(Contract):
  """Agent-facing draft input; ownership, confirmation and signing are server-only."""

  description: Text
  category: Text
  max_cents: Cents
  location: Text | None = None
  valid_until: UtcDatetime | None = None
  currency: Currency = "USD"
  product_constraints: tuple[ProductConstraint, ...] = ()
  max_quantity: Quantity = Field(default=1, validation_alias=AliasChoices("max_quantity", "maximum_quantity"))
  maximum_purchases: Quantity = 1
  allow_subscription: StrictBool = Field(default=False, validation_alias=AliasChoices("allow_subscription", "allow_subscriptions"))
  allow_recurring: StrictBool = Field(default=False, validation_alias=AliasChoices("allow_recurring", "allow_recurring_payments"))
  shipping_constraints: ShippingConstraints | None = None
  merchant_allowlist: tuple[Text, ...] | None = None
  valid_from: UtcDatetime | None = None

  @model_validator(mode="after")
  def validate_draft(self) -> Self:
    if self.valid_from is not None and self.valid_until is not None and self.valid_from >= self.valid_until:
      raise ValueError("draft validity must end after its start")
    if self.merchant_allowlist is not None:
      if not self.merchant_allowlist or len(set(self.merchant_allowlist)) != len(self.merchant_allowlist):
        raise ValueError("merchant_allowlist must be nonempty and unique or null")
    return self


class PurchaseMandate(Contract):
  id: MandateId
  user_id: UserId
  agent_id: AgentId
  description: Text
  category: Text
  max_cents: Cents
  currency: Currency = "USD"
  product_constraints: tuple[ProductConstraint, ...] = ()
  max_quantity: Quantity = Field(default=1, validation_alias=AliasChoices("max_quantity", "maximum_quantity"))
  maximum_purchases: Quantity = 1
  allow_subscription: StrictBool = Field(default=False, validation_alias=AliasChoices("allow_subscription", "allow_subscriptions"))
  allow_recurring: StrictBool = Field(default=False, validation_alias=AliasChoices("allow_recurring", "allow_recurring_payments"))
  shipping_constraints: ShippingConstraints | None = None
  location: Text | None = None
  merchant_allowlist: tuple[Text, ...] | None = None
  valid_from: UtcDatetime
  valid_until: UtcDatetime
  version: Version = 1
  created_at: UtcDatetime
  status: MandateStatus = MandateStatus.PROPOSED
  approved_at: UtcDatetime | None = None
  signature: Signature | None = None
  canonical_payload_hash: Sha256 | None = None

  @model_validator(mode="after")
  def validate_record(self) -> Self:
    if self.valid_from >= self.valid_until or self.created_at >= self.valid_until:
      raise ValueError("mandate validity must end after its start and creation")
    if self.merchant_allowlist is not None:
      if not self.merchant_allowlist:
        raise ValueError("merchant_allowlist must be nonempty or null")
      if len(set(self.merchant_allowlist)) != len(self.merchant_allowlist):
        raise ValueError("merchant_allowlist cannot contain duplicates")
    if self.approved_at is not None:
      if not self.created_at <= self.approved_at < self.valid_until:
        raise ValueError("confirmation must be after creation and before expiry")
    if self.status == MandateStatus.PROPOSED:
      if self.approved_at is not None or self.signature is not None:
        raise ValueError("a proposed mandate cannot claim human confirmation")
    if self.status == MandateStatus.ACTIVE:
      if self.approved_at is None or self.signature is None:
        raise ValueError("active mandates require confirmation and a signature")
    _bind_hash(self, "canonical_payload_hash", mandate_hash(self))
    return self


# Both names identify the same schema; existing agent vocabulary stays usable.
Mandate = PurchaseMandate


class Merchant(Contract):
  name: Text
  descriptor: Text
  mcc: Mcc
  url: Text


class CartItem(Contract):
  name: Text
  quantity: Quantity
  unit_cents: Cents


class CartProposal(Contract):
  """Agent claims only. This schema is never proof of a merchant checkout."""

  merchant: Merchant
  items: Annotated[tuple[CartItem, ...], Field(min_length=1)]
  total_cents: Cents
  currency: Currency = "USD"

  @model_validator(mode="after")
  def validate_total(self) -> Self:
    if sum(item.quantity * item.unit_cents for item in self.items) != self.total_cents:
      raise ValueError("proposal total must equal the sum of proposed items")
    return self


class Cart(CartProposal):
  id: CartId
  mandate_id: MandateId
  cart_hash: Sha256 | None = None

  @model_validator(mode="after")
  def validate_hash(self) -> Self:
    _bind_hash(self, "cart_hash", cart_hash(self))
    return self


class AgentProposalItem(Contract):
  name: Text
  sku: Text | None = None
  quantity: Quantity
  unit_cents: Cents


class AgentPurchaseProposal(Contract):
  """Shopper claims for comparison; contains no trusted merchant or product facts."""

  merchant_name: Text | None = None
  items: Annotated[tuple[AgentProposalItem, ...], Field(min_length=1)]
  total_cents: Cents


class PaymentProposal(Contract):
  mandate_id: MandateId
  checkout_id: Text
  run_id: RunId | None = None
  proposal: AgentPurchaseProposal | None = None


class CanonicalProduct(Contract):
  sku: Text
  merchant_id: Text
  product_name: Text
  product_category: Text
  unit_cents: Cents
  currency: Currency = "USD"
  subscription: StrictBool
  recurring: StrictBool
  billing_interval: Text | None = None
  attributes: tuple[ProductAttribute, ...] = ()


class ProductListing(Contract):
  url: Text
  sku: Text
  content_sha256: Sha256
  fetched_at: UtcDatetime
  excerpt: Text
  trust_classification: Literal[TrustClassification.UNTRUSTED] = (
    TrustClassification.UNTRUSTED
  )


class CheckoutItem(Contract):
  sku: Text
  product_name: Text
  # Null is explicit uncertainty; the verifier must block or request review.
  product_category: Text | None
  quantity: Quantity
  unit_cents: Cents
  recurring: StrictBool
  subscription: StrictBool
  billing_interval: Text | None = None
  attributes: tuple[ProductAttribute, ...] = ()


class CheckoutSource(Contract):
  source_id: Text
  url: Text
  retrieved_at: UtcDatetime
  method: Literal["server_fetch", "authenticated_assertion"]


class CheckoutSnapshot(Contract):
  """A persisted snapshot; source authentication is performed by the backend."""

  checkout_id: Text
  revision: Version
  purchase_attempt_id: PaymentId
  user_id: UserId
  merchant_id: Text
  session_id: Text
  merchant: Merchant
  items: Annotated[tuple[CheckoutItem, ...], Field(min_length=1)]
  currency: Currency = "USD"
  subtotal_cents: Cents
  tax_cents: Cents
  shipping_cents: Cents
  total_cents: Cents
  shipping_country: Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")] | None = None
  shipping_postal_code: Text | None = None
  delivery_at: UtcDatetime | None = None
  expires_at: UtcDatetime
  source: CheckoutSource
  checkout_hash: Sha256 | None = None

  @model_validator(mode="after")
  def validate_record(self) -> Self:
    if sum(item.quantity * item.unit_cents for item in self.items) != self.subtotal_cents:
      raise ValueError("checkout subtotal must equal the item sum")
    if self.subtotal_cents + self.tax_cents + self.shipping_cents != self.total_cents:
      raise ValueError("checkout total must include subtotal, tax and shipping")
    if self.source.retrieved_at >= self.expires_at:
      raise ValueError("checkout must be valid when its snapshot is retrieved")
    _bind_hash(self, "checkout_hash", checkout_hash(self))
    return self


class Check(Contract):
  name: Text
  passed: StrictBool
  detail: Text


REQUIRED_VERIFICATION_CHECKS = frozenset({
  "mandate_confirmed", "mandate_valid", "checkout_authenticated",
  "checkout_integrity", "checkout_valid", "category", "product_constraints",
  "quantity", "purchase_scope", "merchant", "amount", "currency",
  "subscription", "recurring", "shipping",
})


class CheckoutVerification(Contract):
  id: Text
  user_id: UserId
  purchase_attempt_id: PaymentId
  mandate_id: MandateId
  mandate_version: Version
  mandate_hash: Sha256
  checkout_id: Text
  checkout_hash: Sha256
  decision: VerificationDecision
  checks: Annotated[tuple[Check, ...], Field(min_length=1)]
  reasons: tuple[Text, ...] = ()
  verified_at: UtcDatetime

  @model_validator(mode="after")
  def validate_checks(self) -> Self:
    names = [check.name for check in self.checks]
    if len(names) != len(set(names)):
      raise ValueError("verification check names must be unique")
    if self.decision == VerificationDecision.VERIFIED:
      if not all(check.passed for check in self.checks):
        raise ValueError("VERIFIED cannot contain a failed check")
      if not REQUIRED_VERIFICATION_CHECKS.issubset(names):
        raise ValueError("VERIFIED requires every mandatory deterministic check")
    elif not self.reasons:
      raise ValueError("blocked or review decisions require an explanation")
    return self


class SuspiciousSource(Contract):
  url: Text
  sha256: Sha256
  excerpt: Text


class GuardianCheck(Check):
  severity: Literal["block", "review"]
  evidence: tuple[Text, ...] = ()


class GuardianSource(SuspiciousSource):
  excerpt: StrictStr
  phrases: tuple[Text, ...] = ()
  event_id: Text | None = None


class GuardianModelMetadata(Contract):
  status: Literal["skipped", "ok", "unavailable", "invalid_output"]
  error: Text | None = None
  provider: Text | None = None
  model_id: Text | None = None
  cited_sources: tuple[Text, ...] = ()
  intent_match: Literal["match", "mismatch", "unclear"] | None = None
  violated_constraints: tuple[Text, ...] = ()


class Verdict(Contract):
  """Guardian recommendation; not a verification record or payment decision."""

  recommendation: GuardianRecommendation
  authority: Literal["advisory"] = "advisory"
  reasons: tuple[Text, ...] = ()
  explanation: StrictStr | None = None
  checks: tuple[GuardianCheck, ...] = ()
  suspicious_sources: tuple[GuardianSource, ...] = ()
  checkout_id: Text | None = None
  model: GuardianModelMetadata | None = None


# The existing Verdict name stays importable, with the non-authorizing wire schema.
GuardianFindings = Verdict


class GuardianEvaluationRequest(Contract):
  mandate: PurchaseMandate
  checkout: CheckoutSnapshot | None = None
  proposal: AgentPurchaseProposal | None = Field(
    default=None, validation_alias=AliasChoices("proposal", "cart")
  )
  provenance: tuple[dict[str, JsonValue], ...] = ()
  trace: tuple[dict[str, JsonValue], ...] = ()


class AuthorizationGrant(Contract):
  grant_id: Text
  payment_id: PaymentId
  mandate_id: MandateId
  mandate_version: Version
  mandate_hash: Sha256
  user_id: UserId
  verification_id: Text
  verified_checkout_id: Text
  verified_checkout_hash: Sha256
  payment_instrument_id: Text
  merchant_id: Text
  merchant_descriptor: Text
  mcc: Mcc
  authorized_amount_cents: Cents
  currency: Currency = "USD"
  merchant_binding_id: Text
  bound_at: UtcDatetime
  issued_at: UtcDatetime
  expires_at: UtcDatetime
  mandate_expires_at: UtcDatetime
  checkout_expires_at: UtcDatetime
  status: GrantStatus = GrantStatus.ISSUED

  @model_validator(mode="after")
  def validate_validity(self) -> Self:
    if not self.bound_at <= self.issued_at < self.expires_at:
      raise ValueError("grant requires merchant binding before issue and later expiry")
    if self.expires_at > min(self.mandate_expires_at, self.checkout_expires_at):
      raise ValueError("grant cannot outlive mandate or checkout")
    return self


class PreApproval(Contract):
  """Valkey wire record retaining legacy names plus mandatory grant bindings."""

  payment_id: PaymentId
  mandate_id: MandateId
  mandate_version: Version
  user_id: UserId
  card_token: Text
  merchant_descriptor: Text
  mcc: Mcc
  max_cents: Cents
  cart_hash: Sha256 | None = None
  expires_at: UtcDatetime
  grant: AuthorizationGrant

  @model_validator(mode="after")
  def validate_binding(self) -> Self:
    expected = {
      "payment_id": self.grant.payment_id,
      "mandate_id": self.grant.mandate_id,
      "mandate_version": self.grant.mandate_version,
      "user_id": self.grant.user_id,
      "card_token": self.grant.payment_instrument_id,
      "merchant_descriptor": self.grant.merchant_descriptor,
      "mcc": self.grant.mcc,
      "max_cents": self.grant.authorized_amount_cents,
      "expires_at": self.grant.expires_at,
    }
    if any(getattr(self, key) != value for key, value in expected.items()):
      raise ValueError("preapproval fields must exactly match the bound grant")
    return self

  @classmethod
  def from_grant(cls, grant: AuthorizationGrant, cart_hash: str | None = None) -> Self:
    return cls(
      payment_id=grant.payment_id, mandate_id=grant.mandate_id,
      mandate_version=grant.mandate_version, user_id=grant.user_id,
      card_token=grant.payment_instrument_id,
      merchant_descriptor=grant.merchant_descriptor, mcc=grant.mcc,
      max_cents=grant.authorized_amount_cents, cart_hash=cart_hash,
      expires_at=grant.expires_at, grant=grant,
    )


class PaymentRequest(Contract):
  id: PaymentId
  mandate_id: MandateId
  mandate_version: Version
  agent_id: AgentId
  run_id: RunId
  checkout_id: Text
  proposal: AgentPurchaseProposal | None = None
  cart: Cart | None = None
  status: PaymentStatus = PaymentStatus.PENDING_GUARDIAN
  verdict: Verdict | None = None
  verification_id: Text | None = None
  grant_id: Text | None = None
  card_token: Text | None = None
  card_last4: Annotated[StrictStr, Field(pattern=r"^[0-9]{4}$")] | None = None
  created_at: UtcDatetime


class PaymentResponse(Contract):
  """Payment setup/status response. Approved means a grant, not a completed charge."""

  id: PaymentId
  status: Literal[
    "approved", "pending_user", "blocked", "denied", "pending_guardian", "expired", "used"
  ]
  reasons: tuple[Text, ...] = ()
  verification_id: Text | None = None
  grant_id: Text | None = None
  payment_result: PaymentOutcome | None = None

  @model_validator(mode="after")
  def validate_grant_references(self) -> Self:
    if self.status in {"approved", "used"}:
      if self.verification_id is None or self.grant_id is None:
        raise ValueError("approved/used responses require verification and grant references")
    if self.payment_result == PaymentOutcome.APPROVED and self.status not in {"approved", "used"}:
      raise ValueError("an unapproved payment cannot claim successful authorization")
    return self


class AuthorizationAttempt(Contract):
  id: Text
  rail: PaymentRail
  provider_program_id: Text
  provider_event_id: Text
  request_fingerprint: Sha256
  payment_instrument_id: Text
  merchant_id: Text | None = None
  merchant_descriptor: Text
  mcc: Mcc
  amount_cents: Cents
  currency: Currency = "USD"
  request_type: Text
  received_at: UtcDatetime
  checkout_id: Text | None = None
  checkout_hash: Sha256 | None = None


class PaymentDecision(Contract):
  id: Text
  attempt_id: Text
  rail: PaymentRail
  result: PaymentOutcome
  reason: Text
  decision_source: Text
  latency_ms: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
  decided_at: UtcDatetime
  payment_id: PaymentId | None = None
  grant_id: Text | None = None
  verification_id: Text | None = None
  mandate_hash: Sha256 | None = None
  checkout_hash: Sha256 | None = None

  @model_validator(mode="after")
  def validate_approval(self) -> Self:
    if self.result == PaymentOutcome.APPROVED and any(value is None for value in (
      self.payment_id, self.grant_id, self.verification_id,
      self.mandate_hash, self.checkout_hash,
    )):
      raise ValueError("approved decisions require the complete verified grant chain")
    return self


class AuthorizationDecision(PaymentDecision):
  """Normalized legacy ASA decision vocabulary, separate from provider wire types."""

  asa_token: Text
  card_token: Text
  merchant_descriptor: Text
  mcc: Mcc
  amount_cents: Cents


class AgentRun(Contract):
  id: RunId
  agent_id: AgentId
  user_id: UserId
  mandate_id: MandateId
  mandate_version: Version
  mandate_hash: Sha256
  agent_mode: Literal["live", "scripted"]
  status: RunStatus = RunStatus.PENDING
  model: Text | None = None
  provider: Text | None = None
  created_at: UtcDatetime
  started_at: UtcDatetime | None = None
  ended_at: UtcDatetime | None = None

  @model_validator(mode="after")
  def validate_times(self) -> Self:
    if self.started_at is not None and self.started_at < self.created_at:
      raise ValueError("run cannot start before creation")
    if self.ended_at is not None:
      if self.started_at is None or self.ended_at < self.started_at:
        raise ValueError("run end requires an earlier start")
    return self


class AgentTraceEvent(Contract):
  event_id: Text
  run_id: RunId
  agent_id: AgentId
  user_id: UserId
  agent_mode: Literal["live", "scripted"]
  timestamp: UtcDatetime
  phase: Literal["before_tool", "after_tool"]
  tool_name: Text
  tool_use_id: Text
  # Inputs are sanitized by the provenance adapter before storage.
  tool_arguments: dict[str, JsonValue] = Field(default_factory=dict)
  source_reference: Text | None = None
  source_sha256: Sha256 | None = None
  tool_result_summary: Text | None = None
  trust_classification: TrustClassification
  proposed_action: Text | None = None
  policy_decision: Text | None = None
  duration_ms: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] | None = None


class ProvenanceEvent(Contract):
  run_id: RunId
  agent_id: AgentId
  url: Text
  sha256: Sha256
  fetched_at: UtcDatetime
  hidden_text_detected: StrictBool
  suspicious_phrases: tuple[Text, ...] = ()
  snapshot_key: Text | None = None
  excerpt: Text


class SecurityIncident(Contract):
  id: Text
  user_id: UserId
  run_id: RunId
  mandate_id: MandateId
  mandate_version: Version
  mandate_hash: Sha256
  checkout_id: Text | None = None
  checkout_hash: Sha256 | None = None
  verification_id: Text | None = None
  decision_id: Text | None = None
  trace_event_ids: tuple[Text, ...] = ()
  suspicious_sources: tuple[SuspiciousSource, ...] = ()
  violated_checks: Annotated[tuple[Text, ...], Field(min_length=1)]
  explanation: Text
  created_at: UtcDatetime


def _json_value(value: Any) -> Any:
  if isinstance(value, BaseModel):
    return _json_value(value.model_dump(mode="python"))
  if isinstance(value, datetime):
    if value.tzinfo is None or value.utcoffset() is None:
      raise ValueError("canonical timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
  if isinstance(value, Mapping):
    if any(not isinstance(key, str) for key in value):
      raise TypeError("canonical JSON object keys must be strings")
    return {key: _json_value(item) for key, item in value.items()}
  if isinstance(value, (list, tuple)):
    return [_json_value(item) for item in value]
  return value


def canonical_json(data: Any) -> str:
  """Version-1 JSON encoding: sorted keys, preserved array order, UTC, ASCII."""
  return json.dumps(
    _json_value(data), sort_keys=True, separators=(",", ":"), allow_nan=False
  )


def payload_hash(data: Any) -> str:
  return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def mandate_payload(mandate: PurchaseMandate) -> dict[str, Any]:
  # Lifecycle fields change without changing what the human originally approved.
  return {"schema_version": 1, **mandate.model_dump(exclude={
    "status", "approved_at", "signature", "canonical_payload_hash",
  })}


def mandate_hash(mandate: PurchaseMandate) -> str:
  return payload_hash(mandate_payload(mandate))


def cart_payload(cart: Cart | Mapping[str, Any]) -> dict[str, Any]:
  if isinstance(cart, Cart):
    return cart.model_dump(include={"mandate_id", "merchant", "items", "total_cents"})
  # Revalidate the proposal, including USD-only currency, before projection.
  allowed = {"id", "cart_hash", "mandate_id", "merchant", "items", "total_cents", "currency"}
  if set(cart) - allowed:
    raise ValueError("unexpected proposal fields in cart hash input")
  validated = _CartHashInput.model_validate({
    key: value for key, value in cart.items() if key not in {"id", "cart_hash"}
  })
  return validated.model_dump(include={"mandate_id", "merchant", "items", "total_cents"})


class _CartHashInput(CartProposal):
  mandate_id: MandateId


def cart_hash(cart: Cart | Mapping[str, Any]) -> str:
  """Proposal hash matches the four-field legacy agent encoding, never checkout proof."""
  return payload_hash(cart_payload(cart))


def checkout_payload(checkout: CheckoutSnapshot) -> dict[str, Any]:
  payload = checkout.model_dump(exclude={"checkout_hash"})
  # Re-fetching an unchanged checkout changes acquisition time, not purchase facts.
  payload["source"].pop("retrieved_at")
  return {"schema_version": 1, **payload}


def checkout_hash(checkout: CheckoutSnapshot) -> str:
  return payload_hash(checkout_payload(checkout))


def _bind_hash(record: Contract, field: str, expected: str) -> None:
  supplied = getattr(record, field)
  if supplied is not None and supplied != expected:
    raise ValueError(f"{field} does not match its canonical payload")
  object.__setattr__(record, field, expected)
