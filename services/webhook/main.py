"""LEASH payment rail: local authorize + Lithic ASA adapter over shared decide()/Valkey."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from activity_notify import notify_authorization_decided
from asa import (
  ASA_RAIL_LABEL,
  AsaAuthError,
  AsaParseError,
  asa_response,
  asa_secret,
  normalize_asa_request,
  verify_asa_signature,
)
from decide import Decision, GrantSnapshot
from handler import StoreUnavailable, attempt_from_mapping, authorize
from store import MemoryGrantStore, RedisGrantStore

SERVICE = "leash-webhook"
LOCAL_RAIL_LABEL = "local_payment_rail_simulator"

app = FastAPI(title="LEASH Payment Rail", version="0.2.0")

_store: MemoryGrantStore | RedisGrantStore | None = None
_store_mode: Literal["memory", "valkey"] = "memory"


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
  if token != expected:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credential")


def get_store() -> MemoryGrantStore | RedisGrantStore:
  if _store is None:
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="Grant store is not ready",
    )
  return _store


class AuthorizeBody(BaseModel):
  event_id: str = Field(min_length=1, max_length=128)
  request_type: str = "AUTHORIZATION"
  instrument_token: str = Field(min_length=1, max_length=128)
  descriptor: str = Field(min_length=1, max_length=200)
  mcc: str = Field(min_length=2, max_length=8)
  amount_cents: int = Field(ge=0)
  currency: str = Field(min_length=3, max_length=3)
  now: datetime | None = None


class GrantBody(BaseModel):
  grant_id: str
  status: str = "ISSUED"
  mandate_id: str
  mandate_version: int = Field(ge=1)
  instrument_token: str
  descriptor: str
  mcc: str
  authorized_amount_cents: int = Field(ge=0)
  currency: str = "USD"
  expires_at: datetime
  mandate_status: str = "active"
  current_mandate_version: int | None = None
  user_id: str | None = Field(
    default=None,
    description="Optional LEASH usr_… for activity attribution",
  )


class KillswitchBody(BaseModel):
  on: bool


class CardStateBody(BaseModel):
  card_token: str
  state: Literal["OPEN", "PAUSED", "CLOSED"] = "PAUSED"


class SimulateBody(BaseModel):
  card_token: str
  amount_cents: int = Field(ge=0)
  descriptor: str
  mcc: str


class EnrollAsaBody(BaseModel):
  url: str = Field(min_length=8, max_length=500)


def _with_rail(decision: Decision, rail: str) -> Decision:
  return Decision(result=decision.result, reason=decision.reason, rail=rail)


def _schedule_activity(
  background: BackgroundTasks,
  *,
  decision: Decision,
  attempt_event_id: str,
  instrument_token: str,
  amount_cents: int,
  currency: str,
  descriptor: str,
  mcc: str,
  user_id: str | None,
  decision_source: str,
  latency_ms: float,
) -> None:
  background.add_task(
    notify_authorization_decided,
    decision=decision,
    event_id=attempt_event_id,
    instrument_token=instrument_token,
    amount_cents=amount_cents,
    currency=currency,
    descriptor=descriptor,
    mcc=mcc,
    user_id=user_id,
    decision_source=decision_source,
    latency_ms=latency_ms,
  )


@app.on_event("startup")
def on_startup() -> None:
  global _store, _store_mode
  url = os.getenv("VALKEY_URL", "").strip()
  if url:
    _store = RedisGrantStore(url)
    _store_mode = "valkey"
  else:
    _store = MemoryGrantStore()
    _store_mode = "memory"


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, Any]:
  return {
    "status": "ok",
    "service": SERVICE,
    "rails": [LOCAL_RAIL_LABEL, ASA_RAIL_LABEL],
    "asa_hmac_configured": bool(asa_secret()),
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
  }


@app.post("/local/authorize")
def local_authorize(
  body: AuthorizeBody,
  background: BackgroundTasks,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  """Labeled local payment rail. Same decide() path as Lithic ASA."""
  started = time.perf_counter()
  attempt = attempt_from_mapping(body.model_dump(exclude={"now"}))
  try:
    decision = _with_rail(authorize(store, attempt, now=body.now), LOCAL_RAIL_LABEL)
  except StoreUnavailable:
    decision_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
      "result": "ERROR",
      "reason": "state_store_unavailable",
      "rail": LOCAL_RAIL_LABEL,
      "decision_source": "local_rail",
      "latency_ms": decision_ms,
    }
  decision_ms = round((time.perf_counter() - started) * 1000, 2)
  grant = store.get_grant_by_instrument(attempt.instrument_token)
  _schedule_activity(
    background,
    decision=decision,
    attempt_event_id=attempt.event_id,
    instrument_token=attempt.instrument_token,
    amount_cents=attempt.amount_cents,
    currency=attempt.currency,
    descriptor=attempt.descriptor,
    mcc=attempt.mcc,
    user_id=grant.user_id if grant else None,
    decision_source="local_rail",
    latency_ms=decision_ms,
  )
  return {
    **decision.as_dict(),
    "decision_source": "local_rail",
    "latency_ms": decision_ms,
    "event_id": body.event_id,
  }


@app.post("/lithic/asa")
async def lithic_asa(
  request: Request,
  background: BackgroundTasks,
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> JSONResponse:
  """Lithic ASA responder. Public; authenticity via optional HMAC headers."""
  started = time.perf_counter()
  body = await request.body()
  try:
    verify_asa_signature(
      body=body,
      webhook_id=request.headers.get("webhook-id"),
      webhook_timestamp=request.headers.get("webhook-timestamp"),
      webhook_signature=request.headers.get("webhook-signature"),
    )
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

  try:
    decision = _with_rail(authorize(store, attempt), ASA_RAIL_LABEL)
  except StoreUnavailable:
    # 5xx so Lithic retries; not a policy decline.
    return JSONResponse(status_code=503, content={"detail": "state store unavailable"})

  decision_ms = round((time.perf_counter() - started) * 1000, 2)
  grant = store.get_grant_by_instrument(attempt.instrument_token)
  _schedule_activity(
    background,
    decision=decision,
    attempt_event_id=attempt.event_id,
    instrument_token=attempt.instrument_token,
    amount_cents=attempt.amount_cents,
    currency=attempt.currency,
    descriptor=attempt.descriptor,
    mcc=attempt.mcc,
    user_id=grant.user_id if grant else None,
    decision_source="lithic_asa",
    latency_ms=decision_ms,
  )
  return JSONResponse(content=asa_response(decision, transaction_token=attempt.event_id))


@app.put("/internal/grants")
def put_grant(
  body: GrantBody,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, str]:
  """Operator/API seeding of a short-lived grant into Valkey. Not a public mint."""
  grant = GrantSnapshot(
    grant_id=body.grant_id,
    status=body.status.upper(),
    mandate_id=body.mandate_id,
    mandate_version=body.mandate_version,
    instrument_token=body.instrument_token,
    descriptor=body.descriptor,
    mcc=body.mcc,
    authorized_amount_cents=body.authorized_amount_cents,
    currency=body.currency.upper(),
    expires_at=body.expires_at,
    user_id=body.user_id,
  )
  store.put_grant(grant)
  version = body.current_mandate_version or body.mandate_version
  store.set_mandate(body.mandate_id, status=body.mandate_status, version=version)
  return {"status": "ok", "grant_id": grant.grant_id}


@app.post("/internal/killswitch")
def set_killswitch(
  body: KillswitchBody,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  store.set_killswitch(body.on)
  return {"killswitch_on": body.on}


@app.post("/internal/lithic/card-state")
def set_card_state(
  body: CardStateBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Pause/open a Lithic sandbox card (outside the ASA critical path)."""
  from leash_shared.lithic import LithicError, update_card_state

  try:
    card = update_card_state(body.card_token, body.state)
  except LithicError as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from exc
  return {
    "card_token": body.card_token,
    "state": card.get("state") or body.state,
    "provider": "lithic_sandbox",
  }


@app.post("/internal/lithic/simulate")
def simulate_lithic_auth(
  body: SimulateBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Sandbox: ask Lithic to simulate an auth against the enrolled ASA URL."""
  from leash_shared.lithic import LithicError, simulate_authorization

  try:
    result = simulate_authorization(
      card_token=body.card_token,
      amount_cents=body.amount_cents,
      descriptor=body.descriptor,
      mcc=body.mcc,
    )
  except LithicError as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from exc
  return {"provider": "lithic_sandbox", "simulation": result}


@app.post("/internal/lithic/asa/enroll")
def enroll_asa(
  body: EnrollAsaBody,
  _: Annotated[None, Depends(require_internal)],
) -> dict[str, Any]:
  """Enroll this program's ASA responder URL in Lithic sandbox."""
  from leash_shared.lithic import LithicError, enroll_asa_responder

  try:
    result = enroll_asa_responder(body.url)
  except LithicError as exc:
    raise HTTPException(status_code=502, detail=str(exc)) from exc
  return {"provider": "lithic_sandbox", "enrollment": result, "url": body.url}
