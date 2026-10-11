"""Pure payment authorization policy (C03).

No I/O: no SQL, Valkey, LLM, merchant, or network. The Valkey handler loads
state, calls decide(), then atomically commits consumption / cached responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

DecisionResult = Literal["APPROVED", "DECLINED", "ERROR"]

SUPPORTED_REQUEST_TYPES = frozenset({"AUTHORIZATION"})

# Precedence when more than one condition fails (decision_cases.yaml).
REASON_PRECEDENCE = (
  "unsupported_request_type",
  "killswitch_on",
  "no_grant",
  "grant_revoked",
  "grant_consumed",
  "grant_expired",
  "mandate_inactive",
  "mandate_version_mismatch",
  "instrument_mismatch",
  "descriptor_mismatch",
  "mcc_mismatch",
  "currency_mismatch",
  "amount_mismatch",
  "checkout_binding_mismatch",
)


@dataclass(frozen=True)
class AuthorizationAttempt:
  event_id: str
  request_type: str
  instrument_token: str
  descriptor: str
  mcc: str
  amount_cents: int
  currency: str
  checkout_id: str = ""
  checkout_hash: str = ""
  merchant_binding_id: str = ""


@dataclass(frozen=True)
class GrantSnapshot:
  grant_id: str
  status: str
  mandate_id: str
  mandate_version: int
  instrument_token: str
  descriptor: str
  mcc: str
  authorized_amount_cents: int
  currency: str
  expires_at: datetime
  user_id: str = ""
  mandate_hash: str = ""
  checkout_id: str = ""
  checkout_hash: str = ""
  merchant_binding_id: str = ""


@dataclass(frozen=True)
class AuthorityState:
  killswitch_on: bool = False
  mandate_status: str = "active"
  current_mandate_version: int = 1


@dataclass(frozen=True)
class Decision:
  result: DecisionResult
  reason: str
  rail: str = "local_payment_rail_simulator"

  def as_dict(self) -> dict[str, str]:
    return {"result": self.result, "reason": self.reason, "rail": self.rail}


def _utc(value: datetime) -> datetime:
  if value.tzinfo is None:
    return value.replace(tzinfo=timezone.utc)
  return value.astimezone(timezone.utc)


def decide(
  authorization: AuthorizationAttempt,
  grant: GrantSnapshot | None,
  state: AuthorityState,
  *,
  now: datetime,
) -> Decision:
  """Approve only when every grant binding matches exactly; otherwise decline."""
  reasons: list[str] = []

  if authorization.request_type not in SUPPORTED_REQUEST_TYPES:
    reasons.append("unsupported_request_type")
  if state.killswitch_on:
    reasons.append("killswitch_on")
  if grant is None:
    reasons.append("no_grant")
  else:
    status = grant.status.upper()
    if status not in {"ISSUED", "REVOKED", "CONSUMED", "EXPIRED"}:
      return Decision(result="DECLINED", reason="invalid_grant_state")
    if status == "REVOKED":
      reasons.append("grant_revoked")
    if status == "CONSUMED":
      reasons.append("grant_consumed")
    if status == "EXPIRED" or _utc(now) >= _utc(grant.expires_at):
      # Expired clock or explicit EXPIRED status.
      if status != "CONSUMED" and status != "REVOKED":
        reasons.append("grant_expired")
      elif _utc(now) >= _utc(grant.expires_at) and "grant_expired" not in reasons:
        # Still surface expiry when also consumed/revoked only if precedence needs it;
        # consumed/revoked already listed and win on precedence.
        pass
    if state.mandate_status.lower() not in {"active", "confirmed"}:
      reasons.append("mandate_inactive")
    if grant.mandate_version != state.current_mandate_version:
      reasons.append("mandate_version_mismatch")
    if authorization.instrument_token != grant.instrument_token:
      reasons.append("instrument_mismatch")
    if authorization.descriptor != grant.descriptor:
      reasons.append("descriptor_mismatch")
    if authorization.mcc != grant.mcc:
      reasons.append("mcc_mismatch")
    if authorization.currency.upper() != grant.currency.upper():
      reasons.append("currency_mismatch")
    if authorization.amount_cents != grant.authorized_amount_cents:
      reasons.append("amount_mismatch")

    # Legacy pure fixtures have no checkout binding. The HTTP adapter requires
    # a complete R01 AuthorizationGrant; bound grants always enforce correlation.
    if grant.checkout_id and (
      authorization.checkout_id != grant.checkout_id or
      authorization.checkout_hash != grant.checkout_hash or
      authorization.merchant_binding_id != grant.merchant_binding_id
    ):
      reasons.append("checkout_binding_mismatch")

  if not reasons:
    return Decision(result="APPROVED", reason="approved")

  # unsupported_request_type may be DECLINED or ERROR per fixtures.
  primary = min(reasons, key=lambda r: REASON_PRECEDENCE.index(r))
  result: DecisionResult = (
    "ERROR" if primary == "unsupported_request_type" else "DECLINED"
  )
  return Decision(result=result, reason=primary)
