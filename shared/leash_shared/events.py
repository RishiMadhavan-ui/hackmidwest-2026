"""Sanitized event envelopes and the shared Valkey stream wire format."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator

from .models import Contract, Text, UserId, UtcDatetime, canonical_json


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
  AGENT_TOOL_BEFORE = "agent.tool_before"
  AGENT_TOOL_AFTER = "agent.tool_after"
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
  "pan", "cvv", "cvc", "cardnumber", "fullcardnumber", "securitycode",
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
    "apikey", "password", "secret", "signingkey", "accesskey", "privatekey",
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
