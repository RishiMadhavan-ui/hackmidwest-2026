"""Internal local-rail execution controls. These routes never call SQL or an LLM."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StrictInt

from leash_shared.models import AuthorizationGrant, Contract, RunId, UserId, UtcDatetime
from decide import GrantSnapshot
from main import get_store, require_internal

router = APIRouter(prefix="/internal/execution", dependencies=[Depends(require_internal)])
Store = Annotated[object, Depends(get_store)]


class RunLease(Contract):
  run_id: RunId
  user_id: UserId
  generation: StrictInt = Field(ge=1)
  epoch: str = Field(min_length=32, max_length=64)
  lease_until: UtcDatetime


class RunStop(Contract):
  run_id: RunId
  user_id: UserId


class ScopedGrant(Contract):
  grant: AuthorizationGrant
  run_id: RunId
  generation: StrictInt = Field(ge=1)
  epoch: str = Field(min_length=32, max_length=64)
  authorization_event_id: str = Field(min_length=1, max_length=128)


@router.get("/epoch")
def epoch(store: Store):
  return {"epoch": store.epoch(), "rail": "local_payment_rail_simulator"}


@router.post("/lease")
def lease(body: RunLease, store: Store):
  try:
    store.lease_run(body.run_id, body.user_id, body.generation, body.epoch, body.lease_until)
  except ValueError:
    raise HTTPException(409, "Execution is stopped, expired or stale") from None
  return {"run_id": body.run_id, "epoch": body.epoch}


@router.post("/stop")
def stop(body: RunStop, store: Store):
  try:
    store.stop_execution_run(body.run_id, body.user_id)
  except ValueError:
    raise HTTPException(409, "Run ownership mismatch") from None
  return {"run_id": body.run_id, "user_id": body.user_id, "financial_revocation": "enforced"}


@router.put("/grants")
def install(body: ScopedGrant, store: Store):
  g, now = body.grant, datetime.now(timezone.utc)
  if g.status.value != "ISSUED" or not g.issued_at <= now < g.expires_at or (g.expires_at-g.issued_at).total_seconds() > 1800:
    raise HTTPException(422, "Grant validity failed")
  snapshot = GrantSnapshot(grant_id=g.grant_id, status="ISSUED", mandate_id=g.mandate_id,
    mandate_version=g.mandate_version, instrument_token=g.payment_instrument_id,
    descriptor=g.merchant_descriptor, mcc=g.mcc, authorized_amount_cents=g.authorized_amount_cents,
    currency=g.currency, expires_at=g.expires_at, user_id=g.user_id, mandate_hash=g.mandate_hash,
    checkout_id=g.verified_checkout_id, checkout_hash=g.verified_checkout_hash,
    merchant_binding_id=g.merchant_binding_id, run_id=body.run_id,
    execution_generation=body.generation, rail_epoch=body.epoch,
    authorization_event_id=body.authorization_event_id)
  try:
    store.set_mandate(g.mandate_id, status="active", version=g.mandate_version)
    store.put_grant(snapshot)
  except ValueError:
    raise HTTPException(409, "Grant or run authority conflicts") from None
  return {"grant_id": g.grant_id, "epoch": body.epoch}


@router.get("/events/{event_id}")
def event(event_id: str, store: Store):
  result = store.get_event(event_id, event_scope="local")
  return {"epoch": store.epoch(), "event_id": event_id, "found": result is not None,
    "fingerprint": result.fingerprint if result else None,
    "decision": result.decision.as_dict() if result else None}


@router.get("/grants/{grant_id}")
def grant(grant_id: str, store: Store):
  result = store.get_grant(grant_id)
  from store import grant_to_dict
  return {"epoch": store.epoch(), "grant": grant_to_dict(result) if result else None}
