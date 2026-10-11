"""LEASH payment rail: local authorize + Lithic ASA adapter over shared decide()/Valkey."""

from __future__ import annotations

import json
import os
import hmac
import sys
from pathlib import Path
from dataclasses import replace

# Repository checkout and flat /app image layout both locate the shared tree.
sys.path.insert(0, str(next(
  (parent / "shared" for parent in Path(__file__).resolve().parents
   if (parent / "shared").is_dir()),
  Path(__file__).resolve().parent / "shared",
)))
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import Field

from leash_shared.models import AuthorizationGrant, Contract, Cents, Text, Mcc, Sha256, UserId
from activity_notify import start_activity_relay
from asa import (
  ASA_RAIL_LABEL,
  AsaAuthError,
  AsaConfigurationError,
  AsaParseError,
  asa_response,
  asa_secret,
  normalize_asa_request,
  verify_asa_signature,
)
from decide import GrantSnapshot
from handler import StoreUnavailable, attempt_from_mapping, authorize
from store import MemoryGrantStore, RedisGrantStore

SERVICE = "leash-webhook"
LOCAL_RAIL_LABEL = "local_payment_rail_simulator"

app = FastAPI(title="LEASH Payment Rail", version="0.2.0")

_store: MemoryGrantStore | RedisGrantStore | None = None
_store_mode: Literal["memory", "valkey"] = "memory"
_relay = None


def _internal_token() -> str:
  return os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()


def require_internal(
  authorization: Annotated[str | None, Header()] = None,
) -> None:
  expected = _internal_token()
  if not expected:
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="WEBHOOK_INTERNAL_TOKEN is not configured",
    )
  if not authorization or not authorization.lower().startswith("bearer "):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
  token = authorization.split(" ", 1)[1].strip()
  if len(expected) < 32 or not hmac.compare_digest(token, expected):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credential")


def get_store() -> MemoryGrantStore | RedisGrantStore:
  if _store is None:
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="Grant store is not ready",
    )
  return _store


def require_merchant(authorization: Annotated[str | None, Header()] = None):
  expected = os.getenv("WEBHOOK_CHARGE_TOKEN", "").strip()
  if len(expected) < 32 or expected == _internal_token():
    raise HTTPException(503, "Distinct merchant charge credential is not configured")
  if not authorization or not hmac.compare_digest(authorization, "Bearer " + expected):
    raise HTTPException(401, "Invalid merchant credential")


class AuthorizeBody(Contract):
  event_id: Text = Field(max_length=128)
  request_type: str = "AUTHORIZATION"
  instrument_token: Text = Field(max_length=128)
  descriptor: Text = Field(max_length=200)
  mcc: Mcc
  amount_cents: Cents
  currency: Literal["USD"]
  checkout_id: Text
  checkout_hash: Sha256
  merchant_binding_id: Text


class KillswitchBody(Contract):
  user_id: UserId
  on: Literal[True]


class CardStateBody(Contract):
  card_token: Text = Field(max_length=128)
  state: Literal["PAUSED", "CLOSED"] = "PAUSED"


class SimulateBody(Contract):
  card_token: Text = Field(max_length=128)
  amount_cents: Cents
  descriptor: Text = Field(max_length=200)
  mcc: Mcc


class EnrollAsaBody(Contract):
  url: str = Field(min_length=8, max_length=500)


@app.exception_handler(RequestValidationError)
def invalid_request(_, exc):
  # Default errors can echo sensitive raw request fields.
  return JSONResponse(status_code=422, content={"detail": "Invalid rail request"})


@app.on_event("startup")
def on_startup() -> None:
  global _store, _store_mode, _relay
  url = os.getenv("VALKEY_URL", "").strip()
  if url:
    _store = RedisGrantStore(url)
    _store_mode = "valkey"
    _relay = start_activity_relay(_store)
  elif os.getenv("ALLOW_MEMORY_RAIL") == "1":
    _store = MemoryGrantStore()
    _store_mode = "memory"
  else:
    _store = None
    _store_mode = "valkey"


@app.on_event("shutdown")
def on_shutdown():
  global _relay
  if _relay:
    _relay.stop()
    _relay = None


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, Any]:
  return {
    "status": "ok",
    "service": SERVICE,
    "rails": [LOCAL_RAIL_LABEL, ASA_RAIL_LABEL],
    "asa_hmac_configured": bool(asa_secret()),
    "asa_purchase_ready": False,
  }


@app.get("/readyz")
def readyz() -> JSONResponse:
  store = _store
  if store is None or not store.ping():
    return JSONResponse(
      status_code=503,
      content={"detail": "Grant store unavailable", "store": _store_mode},
    )
  return {
    "status": "ok",
    "service": SERVICE,
    "store": _store_mode,
    "rails": [LOCAL_RAIL_LABEL, ASA_RAIL_LABEL],
    "asa_hmac_configured": bool(asa_secret()),
    "asa_purchase_ready": False,
  }


@app.post("/local/authorize")
def local_authorize(
  body: AuthorizeBody,
  _: Annotated[None, Depends(require_merchant)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  """Labeled local payment rail. Same decide() path as Lithic ASA."""
  started = time.perf_counter()
  attempt = attempt_from_mapping(body.model_dump())
  try:
    decision = authorize(store, attempt)
  except StoreUnavailable:
    decision_ms = round((time.perf_counter() - started) * 1000, 2)
    return JSONResponse(
      status_code=503,
      content={
        "result": "ERROR",
        "reason": "state_store_unavailable",
        "rail": LOCAL_RAIL_LABEL,
        "decision_source": "local_rail",
        "latency_ms": decision_ms,
      },
    )
  if decision.result == "ERROR":
    return JSONResponse(
      status_code=503 if decision.reason == "state_store_unavailable" else 409,
      content=decision.as_dict(),
    )
  decision_ms = round((time.perf_counter() - started) * 1000, 2)
  return {
    **decision.as_dict(),
    "decision_source": "local_rail",
    "latency_ms": decision_ms,
    "event_id": body.event_id,
  }


@app.post("/lithic/asa")
async def lithic_asa(
  request: Request,
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> JSONResponse:
  """Signed Lithic ASA responder; checkout correlation remains unavailable."""
  body = bytearray()
  async for chunk in request.stream():
    body.extend(chunk)
    if len(body) > 131072:
      return JSONResponse(status_code=413, content={"detail": "ASA body exceeds limit"})
  body = bytes(body)
  try:
    verify_asa_signature(
      body=body,
      webhook_id=request.headers.get("webhook-id"),
      webhook_timestamp=request.headers.get("webhook-timestamp"),
      webhook_signature=request.headers.get("webhook-signature"),
    )
  except AsaConfigurationError as exc:
    return JSONResponse(status_code=503, content={"detail": str(exc)})
  except AsaAuthError as exc:
    return JSONResponse(status_code=401, content={"detail": str(exc)})

  try:
    payload = json.loads(body.decode("utf-8") or "{}")
  except Exception:
    return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

  try:
    attempt = normalize_asa_request(payload if isinstance(payload, dict) else {})
  except AsaParseError as exc:
    return JSONResponse(status_code=400, content={"detail": str(exc)})

  transaction_token = attempt.event_id
  # Transaction-group token can span multiple attempts; the signed webhook ID
  # remains stable on delivery retry and differs for distinct provider events.
  attempt = replace(attempt, event_id=request.headers["webhook-id"])

  try:
    decision = authorize(store, attempt, event_scope="lithic")
  except StoreUnavailable:
    # 5xx so Lithic retries; not a policy decline.
    return JSONResponse(status_code=503, content={"detail": "state store unavailable"})
  if decision.result == "ERROR":
    return JSONResponse(
      status_code=503 if decision.reason == "state_store_unavailable" else 409,
      content={"detail": decision.reason},
    )

  return JSONResponse(content=asa_response(decision, transaction_token=transaction_token))


@app.put("/internal/grants")
def put_grant(
  body: AuthorizationGrant,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, str]:
  """Operator/API seeding of a short-lived grant into Valkey. Not a public mint."""
  from datetime import timezone

  clock = datetime.now(timezone.utc)
  if (
    body.status.value != "ISSUED"
    or body.expires_at <= clock
    or body.issued_at > clock
    or (body.expires_at - body.issued_at).total_seconds() > 1800
  ):
    raise HTTPException(422, "Only an unexpired verified ISSUED grant may be installed")
  grant = GrantSnapshot(
    grant_id=body.grant_id,
    status=body.status.value,
    mandate_id=body.mandate_id,
    mandate_version=body.mandate_version,
    instrument_token=body.payment_instrument_id,
    descriptor=body.merchant_descriptor,
    mcc=body.mcc,
    authorized_amount_cents=body.authorized_amount_cents,
    currency=body.currency,
    expires_at=body.expires_at,
    user_id=body.user_id,
    mandate_hash=body.mandate_hash,
    checkout_id=body.verified_checkout_id,
    checkout_hash=body.verified_checkout_hash,
    merchant_binding_id=body.merchant_binding_id,
  )
  try:
    store.set_mandate(body.mandate_id, status="active", version=body.mandate_version)
    store.put_grant(grant)
  except ValueError:
    raise HTTPException(409, "Grant or mandate authority conflicts with existing state") from None
  return {"status": "ok", "grant_id": grant.grant_id}


@app.post("/internal/killswitch")
def set_killswitch(
  body: KillswitchBody,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  revoked = store.stop_user(body.user_id)
  return {
    "user_id": body.user_id,
    "killswitch_on": True,
    "unused_grants_revoked": revoked,
    "previous_authorizations_reversed": False,
  }


@app.post("/internal/lithic/card-state")
def set_card_state(
  body: CardStateBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Pause/close a sandbox card; this route cannot activate spending."""
  from leash_shared.lithic import LithicError, update_card_state

  try:
    card = update_card_state(body.card_token, body.state)
  except LithicError:
    raise HTTPException(502, "Provider card-control outcome is unknown; reconcile state") from None
  if card.get("token") != body.card_token:
    raise HTTPException(502, "Provider did not confirm the requested card identity")
  if card.get("state") != body.state and not (
    body.state == "PAUSED" and card.get("state") == "CLOSED"
  ):
    raise HTTPException(502, "Provider did not confirm the requested card state")
  return {
    "card_token": body.card_token,
    "state": card["state"],
    "provider": "lithic_sandbox",
  }


@app.post("/internal/lithic/simulate")
def simulate_lithic_auth(
  body: SimulateBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Sandbox: ask Lithic to simulate an auth against the enrolled ASA URL."""
  # Preserve the operator helper, but do not expose a charge side effect before
  # the durable operation/idempotency/reconciliation layer is implemented.
  raise HTTPException(503, "Simulation requires a durable payment operation; not implemented")


@app.post("/internal/lithic/asa/enroll")
def enroll_asa(
  body: EnrollAsaBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Enroll this program's ASA responder URL in Lithic sandbox."""
  from urllib.parse import urlsplit

  configured = os.getenv("LITHIC_ASA_RESPONDER_URL", "").strip()
  parsed = urlsplit(body.url)
  if (
    not configured
    or body.url != configured
    or parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username
    or parsed.password
  ):
    raise HTTPException(422, "Enrollment requires the configured HTTPS ASA responder URL")
  from leash_shared.lithic import LithicError, enroll_asa_responder

  try:
    result = enroll_asa_responder(body.url)
  except LithicError:
    raise HTTPException(
      502, "Enrollment outcome is unknown; inspect provider configuration before retry"
    ) from None
  return {"provider": "lithic_sandbox", "enrollment": result, "url": body.url}


from execution_routes import router as execution_router  # noqa: E402
app.include_router(execution_router)
