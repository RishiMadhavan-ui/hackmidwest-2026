"""Lithic ASA adapter: HMAC verify, normalize into AuthorizationAttempt, map Decision.

Critical path uses only Valkey via handler.authorize(); no SQL/LLM/merchant calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Any

from decide import AuthorizationAttempt, Decision

ASA_RAIL_LABEL = "lithic_sandbox"


class AsaAuthError(Exception):
  """Invalid or missing ASA HMAC — not a policy decline."""


class AsaParseError(Exception):
  """Malformed ASA body that cannot be decisioned."""


def asa_secret() -> str:
  return os.getenv("LITHIC_ASA_SECRET", "").strip()


def verify_asa_signature(
  *,
  body: bytes,
  webhook_id: str | None,
  webhook_timestamp: str | None,
  webhook_signature: str | None,
  secret: str | None = None,
  max_skew_seconds: int = 300,
) -> None:
  """Svix-style verification used by Lithic Events/ASA HMAC headers.

  When LITHIC_ASA_SECRET is unset, verification is skipped (sandbox bootstrapping).
  When the secret is set, missing/invalid signatures raise AsaAuthError (HTTP 401).
  """
  key = secret if secret is not None else asa_secret()
  if not key:
    return
  if not webhook_id or not webhook_timestamp or not webhook_signature:
    raise AsaAuthError("ASA HMAC headers are required")
  try:
    ts = int(webhook_timestamp)
  except ValueError as exc:
    raise AsaAuthError("Invalid webhook-timestamp") from exc
  if abs(int(time.time()) - ts) > max_skew_seconds:
    raise AsaAuthError("ASA webhook timestamp outside allowed skew")

  # Secrets may be delivered as whsec_<base64> (Svix) or raw.
  raw_key = key
  if key.startswith("whsec_"):
    try:
      raw_key = base64.b64decode(key[len("whsec_") :])
    except Exception as exc:
      raise AsaAuthError("Invalid LITHIC_ASA_SECRET encoding") from exc
  else:
    raw_key = key.encode("utf-8") if isinstance(key, str) else key

  signed = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8") + body
  digest = base64.b64encode(hmac.new(raw_key, signed, hashlib.sha256).digest()).decode("ascii")
  candidates = []
  for part in webhook_signature.split(" "):
    part = part.strip()
    if not part:
      continue
    # Formats: "v1,<b64>" or bare b64
    if "," in part:
      _, _, sig = part.partition(",")
      candidates.append(sig)
    else:
      candidates.append(part)
  if not any(hmac.compare_digest(digest, c) for c in candidates):
    raise AsaAuthError("ASA HMAC signature mismatch")


def _amount_cents(payload: dict[str, Any]) -> int:
  amounts = payload.get("amounts") or {}
  for key in ("merchant", "cardholder", "hold"):
    block = amounts.get(key) or {}
    if isinstance(block, dict) and block.get("amount") is not None:
      return int(block["amount"])
  if payload.get("amount") is not None:
    return int(payload["amount"])
  raise AsaParseError("ASA request missing amount")


def _currency(payload: dict[str, Any]) -> str:
  amounts = payload.get("amounts") or {}
  for key in ("merchant", "cardholder", "hold"):
    block = amounts.get(key) or {}
    if isinstance(block, dict) and block.get("currency"):
      return str(block["currency"]).upper()
  return str(payload.get("currency") or "USD").upper()


def normalize_asa_request(payload: dict[str, Any]) -> AuthorizationAttempt:
  """Map a Lithic ASA JSON body into the pure-rail AuthorizationAttempt."""
  token = payload.get("token") or payload.get("authorization_amount_token")
  if not token:
    raise AsaParseError("ASA request missing transaction token")

  status = str(payload.get("status") or "AUTHORIZATION").upper()
  # Treat financial auths like purchases for the MVP exact-match rail.
  if status in {"AUTHORIZATION", "FINANCIAL_AUTHORIZATION"}:
    request_type = "AUTHORIZATION"
  else:
    request_type = status

  merchant = payload.get("merchant") or {}
  card = payload.get("card") or {}
  instrument = card.get("token") or payload.get("card_token")
  if not instrument:
    raise AsaParseError("ASA request missing card token")

  descriptor = (
    merchant.get("descriptor")
    or merchant.get("acceptor_id")
    or payload.get("merchant_descriptor")
    or ""
  )
  mcc = str(merchant.get("mcc") or payload.get("mcc") or "")
  if not descriptor or not mcc:
    raise AsaParseError("ASA request missing merchant descriptor or MCC")

  return AuthorizationAttempt(
    event_id=str(token),
    request_type=request_type,
    instrument_token=str(instrument),
    descriptor=str(descriptor),
    mcc=mcc,
    amount_cents=_amount_cents(payload),
    currency=_currency(payload),
  )


def decision_to_asa_result(decision: Decision) -> str:
  """Map LEASH Decision to a Lithic ASA result enum value."""
  if decision.result == "APPROVED":
    return "APPROVED"
  reason = decision.reason
  if reason == "killswitch_on":
    return "CARD_PAUSED"
  if reason in {
    "no_grant",
    "grant_revoked",
    "grant_consumed",
    "grant_expired",
    "mandate_inactive",
    "mandate_version_mismatch",
    "instrument_mismatch",
  }:
    return "UNAUTHORIZED_MERCHANT"
  if reason in {
    "descriptor_mismatch",
    "mcc_mismatch",
    "currency_mismatch",
    "amount_mismatch",
  }:
    return "UNAUTHORIZED_MERCHANT"
  if reason == "unsupported_request_type":
    return "UNAUTHORIZED_MERCHANT"
  return "SUSPECTED_FRAUD"


def asa_response(decision: Decision, *, transaction_token: str) -> dict[str, str]:
  return {
    "result": decision_to_asa_result(decision),
    "token": transaction_token,
  }
