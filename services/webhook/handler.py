"""Local / ASA authorization handler: Valkey I/O + pure decide() (C04)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from decide import AuthorizationAttempt, Decision, decide
from store import GrantStore, event_fingerprint


class StoreUnavailable(RuntimeError):
  pass


def authorize(
  store: GrantStore,
  attempt: AuthorizationAttempt,
  *,
  now: datetime | None = None,
) -> Decision:
  """Authorize one attempt. Fail closed if the state store is unavailable."""
  clock = now or datetime.now(timezone.utc)
  payload = {
    "event_id": attempt.event_id,
    "request_type": attempt.request_type,
    "instrument_token": attempt.instrument_token,
    "descriptor": attempt.descriptor,
    "mcc": attempt.mcc,
    "amount_cents": attempt.amount_cents,
    "currency": attempt.currency,
  }
  fingerprint = event_fingerprint(payload)

  try:
    cached = store.get_event(attempt.event_id)
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  if cached is not None:
    if cached.fingerprint != fingerprint:
      return Decision(result="ERROR", reason="event_payload_mismatch")
    return cached.decision

  try:
    grant = store.get_grant_by_instrument(attempt.instrument_token)
    state = store.load_state(grant)
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  decision = decide(attempt, grant, state, now=clock)
  consume = decision.result == "APPROVED" and grant is not None

  try:
    status, committed = store.commit_decision(
      grant_id=grant.grant_id if grant else None,
      event_id=attempt.event_id,
      fingerprint=fingerprint,
      decision=decision,
      consume=consume,
    )
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  if status == "store_error":
    return Decision(result="ERROR", reason="state_store_unavailable")
  return committed


def attempt_from_mapping(data: dict[str, Any]) -> AuthorizationAttempt:
  return AuthorizationAttempt(
    event_id=str(data["event_id"]),
    request_type=str(data["request_type"]),
    instrument_token=str(data["instrument_token"]),
    descriptor=str(data["descriptor"]),
    mcc=str(data["mcc"]),
    amount_cents=int(data["amount_cents"]),
    currency=str(data["currency"]),
  )
