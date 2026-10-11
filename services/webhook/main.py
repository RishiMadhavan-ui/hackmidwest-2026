"""LEASH payment rail: labeled local authorize + Valkey grant store (C03/C04).

Lithic ASA adapter lands later behind the same decide()/handler path.
"""

from __future__ import annotations

import os
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import Field

from leash_shared.models import AuthorizationGrant, Contract, Cents, Text, Mcc, Sha256, UserId
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


@app.on_event("startup")
def on_startup() -> None:
  global _store, _store_mode
  url = os.getenv("VALKEY_URL", "").strip()
  if url:
    _store = RedisGrantStore(url)
    _store_mode = "valkey"
  elif os.getenv("ALLOW_MEMORY_RAIL") == "1":
    _store = MemoryGrantStore()
    _store_mode = "memory"
  else:
    _store = None
    _store_mode = "valkey"


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
  _: Annotated[None, Depends(require_merchant)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, Any]:
  """Labeled local payment rail. Same decide() path Lithic ASA will use."""
  started = time.perf_counter()
  attempt = attempt_from_mapping(body.model_dump())
  try:
    decision = authorize(store, attempt)
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
  body: AuthorizationGrant,
  _: Annotated[None, Depends(require_internal)],
  store: Annotated[MemoryGrantStore | RedisGrantStore, Depends(get_store)],
) -> dict[str, str]:
  """Operator/API seeding of a short-lived grant into Valkey. Not a public mint."""
  from datetime import timezone

  if body.status.value != "ISSUED" or body.expires_at <= datetime.now(timezone.utc):
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
