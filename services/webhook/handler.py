"""Local / ASA authorization handler: Valkey I/O + pure decide() (C04)."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import hashlib
import sys
from pathlib import Path
from typing import Any

# Repository checkout and flat /app image layout both locate the shared tree.
sys.path.insert(0, str(next(
  (parent / "shared" for parent in Path(__file__).resolve().parents
   if (parent / "shared").is_dir()),
  Path(__file__).resolve().parent / "shared",
)))
from leash_shared.events import sanitize_event_data

from decide import AuthorizationAttempt, Decision, decide
from store import GrantStore, event_fingerprint


class StoreUnavailable(RuntimeError):
  pass


def authorize(
  store: GrantStore,
  attempt: AuthorizationAttempt,
  *,
  now: datetime | None = None,
  event_scope: str = "local",
) -> Decision:
  """Authorize one attempt. Fail closed if the state store is unavailable."""
  clock = now or datetime.now(timezone.utc)
  if event_scope not in {"local", "lithic"}:
    raise ValueError("Unknown rail scope")
  rail = "lithic_sandbox" if event_scope == "lithic" else "local_payment_rail_simulator"
  payload = {
    "event_id": attempt.event_id,
    "request_type": attempt.request_type,
    "instrument_token": attempt.instrument_token,
    "descriptor": attempt.descriptor,
    "mcc": attempt.mcc,
    "amount_cents": attempt.amount_cents,
    "currency": attempt.currency,
    "checkout_id": attempt.checkout_id,
    "checkout_hash": attempt.checkout_hash,
    "merchant_binding_id": attempt.merchant_binding_id,
    "event_scope": event_scope,
  }
  fingerprint = event_fingerprint(payload)

  try:
    cached = store.get_event(attempt.event_id, event_scope=event_scope)
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  if cached is not None:
    if cached.fingerprint != fingerprint:
      return Decision(result="ERROR", reason="event_payload_mismatch", rail=rail)
    return cached.decision

  try:
    grant = store.get_grant_by_instrument(attempt.instrument_token)
    state = store.load_state(grant)
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  decision = decide(attempt, grant, state, now=clock)
  if grant and grant.authorization_event_id and grant.authorization_event_id != attempt.event_id:
    decision = Decision("DECLINED", "authorization_event_mismatch")
  # Provider ASA does not carry authenticated SKU/checkout correlation. A card
  # matched to a grant cannot distinguish the signature same-price substitution.
  # Keep this adapter fail-closed until a trusted correlation protocol exists.
  if event_scope == "lithic" and decision.result == "APPROVED":
    decision = Decision("DECLINED", "checkout_correlation_unavailable")
  decision = replace(decision, rail=rail)
  consume = decision.result == "APPROVED" and grant is not None
  event_record = {
    "event_id": "evt_rail_" + hashlib.sha256((rail + ":" + attempt.event_id).encode()).hexdigest(),
    "type": "authorization.decided",
    "user_id": grant.user_id if grant else "",
    "data": {
      "event_id": attempt.event_id,
      "amount_cents": attempt.amount_cents,
      "currency": attempt.currency,
      "descriptor": attempt.descriptor,
      "mcc": attempt.mcc,
      "decision_source": "lithic_asa" if event_scope == "lithic" else "local_rail",
      "provider": "lithic_sandbox" if event_scope == "lithic" else "local_rail",
      "decided_at": clock.isoformat(),
    },
  }
  event_record["data"] = sanitize_event_data(event_record["data"])

  try:
    status, committed = store.commit_decision(
      grant_id=grant.grant_id if grant else None,
      event_id=attempt.event_id,
      fingerprint=fingerprint,
      decision=decision,
      consume=consume,
      now=clock,
      grant=grant,
      event_scope=event_scope,
      event_record=event_record,
    )
  except Exception as exc:
    raise StoreUnavailable("state store unavailable") from exc

  if status == "store_error":
    return Decision(result="ERROR", reason="state_store_unavailable", rail=rail)
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
    checkout_id=str(data.get("checkout_id", "")),
    checkout_hash=str(data.get("checkout_hash", "")),
    merchant_binding_id=str(data.get("merchant_binding_id", "")),
  )
