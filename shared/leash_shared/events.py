"""Sanitized event envelopes and the shared Valkey stream wire format."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self
from uuid import uuid4

from pydantic import Field, JsonValue, StrictBool, StrictStr, TypeAdapter, field_validator, model_validator

from .models import (
  AgentId, Contract, RunId, Sha256, Text, TrustClassification, UserId, UtcDatetime,
  canonical_json,
)


EVENT_STREAM = "leash:events"
REDACTED = "[REDACTED]"


class EventType(StrEnum):
  MANDATE_PROPOSED = "mandate.proposed"
  MANDATE_APPROVED = "mandate.approved"
  MANDATE_UPDATED = "mandate.updated"
  MANDATE_REVOKED = "mandate.revoked"
  MANDATE_EXPIRED = "mandate.expired"
  AGENT_RUN_STARTED = "agent.run_started"
  AGENT_RUN_COMPLETED = "agent.run_completed"
  AGENT_RUN_FAILED = "agent.run_failed"
  AGENT_STEP = "agent.step"
  AGENT_TOOL_BEFORE = "agent.tool.before"
  AGENT_TOOL_AFTER = "agent.tool.after"
  PROVENANCE_SOURCE = "provenance.source"
  PROVENANCE_RECORDED = "provenance.recorded"
  CHECKOUT_VERIFIED = "checkout.verified"
  CHECKOUT_BLOCKED = "checkout.blocked"
  CHECKOUT_REQUIRES_REVIEW = "checkout.requires_review"
  PAYMENT_REQUESTED = "payment.requested"
  GUARDIAN_VERDICT = "guardian.verdict"
  PAYMENT_PENDING_USER = "payment.pending_user"
  PAYMENT_APPROVED = "payment.approved"
  PAYMENT_DENIED = "payment.denied"
  GRANT_ISSUED = "grant.issued"
  GRANT_CONSUMED = "grant.consumed"
  GRANT_EXPIRED = "grant.expired"
  GRANT_REVOKED = "grant.revoked"
  CARD_ISSUED = "card.issued"
  AUTHORIZATION_DECIDED = "authorization.decided"
  SECURITY_INCIDENT_RECORDED = "security.incident_recorded"
  KILLSWITCH_CHANGED = "killswitch.changed"


_SENSITIVE_NAMES = frozenset({
  "pan", "cvv", "cvv2", "cvc", "cvc2", "cardnumber", "fullcardnumber", "securitycode",
  "apikey", "authorization", "bearertoken", "accesstoken", "refreshtoken",
  "password", "secret", "token", "user_token", "usertoken",
  "agenttokenshopper", "mandatesigningkey", "webhooksignature",
  "awsaccesskeyid", "objaccesskeyid", "awssecretaccesskey",
})
_PAN = re.compile(r"(?<![A-Za-z0-9_])(?:\d[ -]?){12,18}\d(?![A-Za-z0-9_])")
_BEARER = re.compile(r"\bBearer\s+[^\s\"',;]+", re.IGNORECASE)
_LABELLED_SECRET = re.compile(
  r"\b(?:pan|card[ _-]?number|cvv|cvc|security[ _-]?code|api[ _-]?key|password|secret|"
  r"access[ _-]?token|refresh[ _-]?token)\s*[:=]\s*[^\s,;]+",
  re.IGNORECASE,
)


def _sensitive(name: str) -> bool:
  normalized = re.sub(r"[^a-z0-9]", "", name.lower())
  return normalized in _SENSITIVE_NAMES or normalized.startswith("agenttoken") or normalized.endswith((
    "apikey", "password", "secret", "secretkey", "signingkey", "accesskey", "privatekey",
  ))


def _safe_text(value: str) -> str:
  value = _PAN.sub(REDACTED, value)
  value = _BEARER.sub("Bearer " + REDACTED, value)
  return _LABELLED_SECRET.sub(REDACTED, value)


def sanitize_event_data(value: Any) -> Any:
  """Redact known secrets; callers still allowlist/summarize untrusted tool text."""
  if hasattr(value, "model_dump"):
    value = value.model_dump(mode="json")
  if isinstance(value, Mapping):
    if any(not isinstance(key, str) for key in value):
      raise ValueError("event data keys must be strings")
    # Trace arguments can arrive as typed name/value attributes.
    sensitive_attribute = isinstance(value.get("name"), str) and _sensitive(value["name"])
    return {
      key: REDACTED if _sensitive(key) or (key == "value" and sensitive_attribute)
      else sanitize_event_data(item)
      for key, item in value.items()
    }
  if isinstance(value, (tuple, list)):
    return [sanitize_event_data(item) for item in value]
  if isinstance(value, str):
    return _safe_text(value)
  if isinstance(value, int) and not isinstance(value, bool):
    # A PAN may be supplied as a numeric tool argument rather than a string.
    if 13 <= len(str(abs(value))) <= 19:
      return REDACTED
  return value


class AgentReportedEvent(Contract):
  """Agent intake identity; the API derives user ownership from authentication."""

  event_id: Text
  run_id: RunId
  agent_id: AgentId
  agent_mode: Literal["live", "scripted"]
  timestamp: UtcDatetime


class AgentToolTraceInput(AgentReportedEvent):
  type: Literal["agent.tool.before", "agent.tool.after"]
  tool_name: Text
  tool_use_id: Text
  tool_arguments: dict[str, JsonValue] = Field(default_factory=dict)
  source_reference: Text | None = None
  # Preserve the agent's label as a claim; normalization never promotes it.
  trust_classification: Text
  proposed_action: Text | None = None
  tool_result_summary: Text | None = None
  policy_decision: Text | None = None
  duration_ms: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] | None = None
  status: Text | None = None
  error: Text | None = None

  @field_validator("tool_arguments", "source_reference", "proposed_action",
                   "tool_result_summary", "policy_decision", "error", mode="before")
  @classmethod
  def sanitize_trace(cls, value: Any) -> Any:
    safe = sanitize_event_data(value)
    canonical_json(safe)
    return safe


class SnapshotMetadata(Contract):
  storage: Literal["none", "object_storage"]
  bucket: Text | None = None
  key: Text | None = None
  reason: Text | None = None
  stored_sha256: Sha256 | None = None

  @model_validator(mode="after")
  def validate_reference(self) -> Self:
    if self.storage == "object_storage" and (self.bucket is None or self.key is None):
      raise ValueError("object storage snapshots require bucket and key")
    if self.storage == "none" and any(value is not None for value in (self.bucket, self.key, self.stored_sha256)):
      raise ValueError("unavailable snapshot cannot claim a stored object")
    return self


class SourceProvenanceInput(AgentReportedEvent):
  type: Literal["provenance.source"]
  url: Text
  sha256: Sha256
  tool_use_id: Text
  http_status: Annotated[int, Field(strict=True, ge=100, le=599)]
  fetched_at: UtcDatetime
  trust_classification: Text
  hidden_text_detected: StrictBool
  suspicious_phrases: tuple[Text, ...] = ()
  hidden_reasons: tuple[Text, ...] = ()
  hidden_suspicious_phrases: tuple[Text, ...] = ()
  excerpt: StrictStr
  snapshot: SnapshotMetadata | None = None

  @field_validator("url", "suspicious_phrases", "hidden_reasons",
                   "hidden_suspicious_phrases", "excerpt", "snapshot", mode="before")
  @classmethod
  def sanitize_source(cls, value: Any) -> Any:
    safe = sanitize_event_data(value)
    canonical_json(safe)
    return safe


ProvenanceInput = Annotated[
  AgentToolTraceInput | SourceProvenanceInput, Field(discriminator="type")
]
_PROVENANCE_INPUT = TypeAdapter(ProvenanceInput)


def parse_provenance(payload: Mapping[str, Any]) -> AgentToolTraceInput | SourceProvenanceInput:
  """Parse the two POST /provenance bodies; routes/auth/persistence are R06 work."""
  return _PROVENANCE_INPUT.validate_python(payload)


class AuditEvent(Contract):
  event_id: Text = Field(default_factory=lambda: "evt_" + uuid4().hex)
  type: EventType
  at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
  user_id: UserId
  data: dict[str, JsonValue]

  @field_validator("data", mode="before")
  @classmethod
  def sanitize_data(cls, value: Any) -> Any:
    safe = sanitize_event_data(value)
    # Reject nonfinite numbers and non-JSON objects before an event is persisted.
    canonical_json(safe)
    return safe


Event = AuditEvent


def agent_report_event(
  report: AgentToolTraceInput | SourceProvenanceInput, *,
  user_id: str, authenticated_agent_id: str, authorized_run_id: str,
  authorized_agent_mode: Literal["live", "scripted"],
  configured_snapshot_bucket: str | None = None,
) -> AuditEvent:
  """Normalize only after token/run ownership checks, never as payment authority."""
  # Revalidate nested mutable arguments at the persistence boundary.
  report = parse_provenance(report.model_dump(mode="json"))
  if report.agent_id != authenticated_agent_id or report.run_id != authorized_run_id:
    raise ValueError("agent/run identity must match the authenticated authorized subject")
  if report.agent_mode != authorized_agent_mode:
    raise ValueError("reported agent mode must match the registered authorized run")
  data = report.model_dump(mode="json", exclude={"type"})
  data["evidence_origin"] = "agent_reported"
  data["authoritative"] = False
  if isinstance(report, AgentToolTraceInput):
    data["reported_trust_classification"] = data["trust_classification"]
    data["trust_classification"] = TrustClassification.AGENT_PROPOSAL.value
  else:
    snapshot = report.snapshot
    if snapshot is not None and snapshot.storage == "object_storage":
      if configured_snapshot_bucket is None or snapshot.bucket != configured_snapshot_bucket:
        raise ValueError("snapshot bucket must match configured authorized storage")
      if snapshot.key != f"runs/{report.run_id}/{report.sha256}.html":
        raise ValueError("snapshot key must match the authorized run and source hash")
      data["snapshot_key"] = snapshot.key
    data["reported_trust_classification"] = data["trust_classification"]
    data["trust_classification"] = TrustClassification.UNTRUSTED.value
  return AuditEvent(
    event_id=report.event_id, type=report.type, at=report.timestamp,
    user_id=user_id, data=data,
  )


class EventStreamClient(Protocol):
  async def xadd(self, name: str, fields: Mapping[str, str]) -> str | bytes: ...


def event_fields(event: AuditEvent) -> dict[str, str]:
  """Fields for XADD, usable inside the rail's atomic state/event transaction."""
  # Revalidate at the write boundary: frozen models may still hold mutable data.
  safe = AuditEvent.model_validate(event.model_dump(mode="python"))
  return {"event": canonical_json(safe)}


async def publish(client: EventStreamClient, event: AuditEvent) -> str:
  """Publish once; failures propagate. ASA must atomically commit state + event."""
  stream_id = await client.xadd(EVENT_STREAM, event_fields(event))
  if isinstance(stream_id, bytes):
    stream_id = stream_id.decode("utf-8")
  if not isinstance(stream_id, str) or not stream_id:
    raise ValueError("event stream did not return an entry ID")
  return stream_id
