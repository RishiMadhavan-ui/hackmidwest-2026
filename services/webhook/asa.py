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


class AsaConfigurationError(Exception):
  """Missing/invalid server key: unavailable, never an unauthenticated rail."""


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

  A configured base64 secret is mandatory. Authentication failure is not a
  financial decline. See https://docs.lithic.com/docs/events-api.
  """
  key = secret if secret is not None else asa_secret()
  if not key:
    raise AsaConfigurationError("ASA signing key is not configured")
  try:
    raw_key = base64.b64decode(key.removeprefix("whsec_"), validate=True)
    if not raw_key:
      raise ValueError()
  except (ValueError, TypeError):
    raise AsaConfigurationError("ASA signing key is invalid") from None
  if not webhook_id or not webhook_timestamp or not webhook_signature:
    raise AsaAuthError("ASA HMAC headers are required")
  if len(webhook_id) > 128 or len(webhook_timestamp) > 20 or len(webhook_signature) > 2048:
    raise AsaAuthError("Invalid ASA HMAC headers")
  try:
    ts = int(webhook_timestamp)
  except ValueError as exc:
    raise AsaAuthError("Invalid webhook-timestamp") from exc
  if abs(int(time.time()) - ts) > max_skew_seconds:
    raise AsaAuthError("ASA webhook timestamp outside allowed skew")

  signed = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8") + body
  digest = base64.b64encode(hmac.new(raw_key, signed, hashlib.sha256).digest()).decode("ascii")
  candidates = []
  for part in webhook_signature.split(" "):
    part = part.strip()
    if not part:
      continue
    if part.startswith("v1,"):
      _, _, sig = part.partition(",")
      candidates.append(sig)
  if not any(hmac.compare_digest(digest, c) for c in candidates):
    raise AsaAuthError("ASA HMAC signature mismatch")


def _amount_and_currency(payload: dict[str, Any]) -> tuple[int, str]:
  amounts = payload.get("amounts")
  if not isinstance(amounts, dict) or not isinstance(amounts.get("merchant"), dict):
    raise AsaParseError("ASA requires structured merchant amount and currency")
  merchant = amounts["merchant"]
  amount, currency = merchant.get("amount"), merchant.get("currency")
  if type(amount) is not int or not 0 <= amount <= 9223372036854775807:
    raise AsaParseError("ASA amount must be nonnegative integer minor units")
  if currency != "USD":
    raise AsaParseError("ASA requires explicit USD currency")
  for name in ("cardholder", "hold"):
    if name in amounts:
      block = amounts[name]
      if (
        not isinstance(block, dict)
        or type(block.get("amount")) is not int
        or (block.get("amount") != amount or block.get("currency") != currency)
      ):
        raise AsaParseError("ASA amounts/currencies differ; exact USD purchase is required")
  if payload.get("cash_amount", 0) != 0 or payload.get("acquirer_fee", 0) != 0:
    raise AsaParseError("ASA cash and extra fees are unsupported")
  return amount, currency


def _text(value: Any, field: str, limit: int = 128) -> str:
  if not isinstance(value, str) or not value.strip() or len(value) > limit:
    raise AsaParseError(f"ASA request missing or invalid {field}")
  return value


def normalize_asa_request(payload: dict[str, Any]) -> AuthorizationAttempt:
  """Map a Lithic ASA JSON body into the pure-rail AuthorizationAttempt."""
  token = _text(payload.get("token"), "transaction token")
  status = _text(payload.get("status"), "status")
  if (
    payload.get("event_type", "card_authorization.approval_request")
    != "card_authorization.approval_request"
  ):
    raise AsaParseError("Unsupported ASA event type")
  # Treat financial auths like purchases for the MVP exact-match rail.
  if status in {"AUTHORIZATION", "FINANCIAL_AUTHORIZATION"}:
    request_type = "AUTHORIZATION"
  else:
    request_type = status

  merchant, card = payload.get("merchant"), payload.get("card")
  if not isinstance(merchant, dict) or not isinstance(card, dict):
    raise AsaParseError("ASA requires merchant and card objects")
  instrument = _text(card.get("token"), "card token")
  descriptor = _text(merchant.get("descriptor"), "merchant descriptor", 200)
  mcc = _text(merchant.get("mcc"), "MCC", 4)
  if len(mcc) != 4 or not mcc.isascii() or not mcc.isdecimal():
    raise AsaParseError("ASA MCC must be a four-digit string")
  amount, currency = _amount_and_currency(payload)

  return AuthorizationAttempt(
    event_id=str(token),
    request_type=request_type,
    instrument_token=str(instrument),
    descriptor=str(descriptor),
    mcc=mcc,
    amount_cents=amount,
    currency=currency,
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
