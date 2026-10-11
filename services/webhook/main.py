"""LEASH payment rail: labeled local authorize + Valkey grant store (C03/C04).

Lithic ASA adapter lands later behind the same decide()/handler path.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from decide import GrantSnapshot
from handler import StoreUnavailable, attempt_from_mapping, authorize
from store import MemoryGrantStore, RedisGrantStore

SERVICE = "leash-webhook"
RAIL_LABEL = "local_payment_rail_simulator"

app = FastAPI(title="LEASH Payment Rail", version="0.1.0")

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


class KillswitchBody(BaseModel):
  on: bool


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
def health() -> dict[str, str]:
  return {"status": "ok", "service": SERVICE, "rail": RAIL_LABEL}


@app.get("/readyz")
def readyz() -> JSONResponse:
  store = _store
  if store is None or not store.ping():
    return JSONResponse(
      status_code=503,
      content={"detail": "Grant store unavailable", "store": _store_mode},
    )
  return {"status": "ok", "service": SERVICE, "store": _store_mode, "rail": RAIL_LABEL}


@app.post("/local/authorize")
def local_authorize(
  body: AuthorizeBody,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  """Labeled local payment rail. Same decide() path Lithic ASA will use."""
  started = time.perf_counter()
  attempt = attempt_from_mapping(body.model_dump(exclude={"now"}))
  try:
    decision = authorize(store, attempt, now=body.now)
  except StoreUnavailable:
    decision_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
      "result": "ERROR",
      "reason": "state_store_unavailable",
      "rail": RAIL_LABEL,
      "decision_source": "local_rail",
      "latency_ms": decision_ms,
    }
  decision_ms = round((time.perf_counter() - started) * 1000, 2)
  return {
    **decision.as_dict(),
    "decision_source": "local_rail",
    "latency_ms": decision_ms,
    "event_id": body.event_id,
  }


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
