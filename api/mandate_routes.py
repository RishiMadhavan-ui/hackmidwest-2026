"""REST boundary: agents draft, authenticated humans confirm exact content."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import StrictBool, model_validator

from db import get_conn
from leash_shared.models import (
  AgentRun, AgentRunRegistration, Contract, MandateId, MandateProposal,
  MandateStatus, PurchaseMandate, Sha256, Version,
)
from mandate_service import (
  approve, current_mandate, list_mandates, propose, register_run, replace,
  revoke, scope_head, utc_now, version_record,
)
from principals import Principal, require_agent, require_human, require_reader

router = APIRouter(tags=["mandates"])
Agent = Annotated[Principal, Depends(require_agent)]
Human = Annotated[Principal, Depends(require_human)]
Reader = Annotated[Principal, Depends(require_reader)]


class VersionBinding(Contract):
  version: Version
  canonical_payload_hash: Sha256


class MandateConfirmation(VersionBinding):
  confirmed: StrictBool

  @model_validator(mode="after")
  def require_confirmation(self):
    if not self.confirmed:
      raise ValueError("explicit human confirmation is required")
    return self


class MandateReplacement(VersionBinding):
  proposal: MandateProposal


class MandateList(Contract):
  items: tuple[PurchaseMandate, ...]


@router.get("/identity")
def identity(principal: Human) -> dict[str, str]:
  return {"user_id": principal.user_id, "role": "human"}


@router.post("/mandates/propose", response_model=PurchaseMandate, status_code=201)
def propose_mandate(body: MandateProposal, principal: Agent):
  with get_conn() as conn:
    record = propose(conn, body, principal, now=utc_now())
  return record


@router.get("/mandates", response_model=MandateList)
def get_mandates(principal: Reader, status: MandateStatus | None = None):
  with get_conn() as conn:
    records = list_mandates(conn, principal, status=status, now=utc_now())
  return MandateList(items=tuple(records))


@router.get("/mandates/{mandate_id}", response_model=PurchaseMandate)
def get_mandate(mandate_id: MandateId, principal: Reader):
  with get_conn() as conn:
    record = current_mandate(conn, mandate_id, principal, now=utc_now())
  return record


@router.get("/mandates/{mandate_id}/versions", response_model=MandateList)
def mandate_history(mandate_id: MandateId, principal: Human):
  with get_conn() as conn:
    scope_head(conn, mandate_id, principal)
    versions = conn.execute("SELECT version FROM mandate_versions WHERE mandate_id = %s ORDER BY version", (mandate_id,)).fetchall()
    now = utc_now()
    records = [version_record(conn, mandate_id, row["version"], now=now) for row in versions]
  return MandateList(items=tuple(records))


@router.post("/mandates/{mandate_id}/approve", response_model=PurchaseMandate)
def approve_mandate(mandate_id: MandateId, body: MandateConfirmation, principal: Human):
  with get_conn() as conn:
    record = approve(conn, mandate_id, principal, version=body.version,
                     content_hash=body.canonical_payload_hash, now=utc_now())
  return record


@router.patch("/mandates/{mandate_id}", response_model=PurchaseMandate)
def replace_mandate(mandate_id: MandateId, body: MandateReplacement, principal: Human):
  with get_conn() as conn:
    record = replace(conn, mandate_id, principal, version=body.version,
                     content_hash=body.canonical_payload_hash, proposal=body.proposal, now=utc_now())
  return record


@router.post("/mandates/{mandate_id}/revoke", response_model=PurchaseMandate)
def revoke_mandate(mandate_id: MandateId, body: VersionBinding, principal: Human):
  with get_conn() as conn:
    record = revoke(conn, mandate_id, principal, version=body.version,
                    content_hash=body.canonical_payload_hash, now=utc_now())
  return record


@router.post("/agent-runs", response_model=AgentRun, status_code=201, tags=["agent runs"])
def post_agent_run(body: AgentRunRegistration, principal: Agent):
  with get_conn() as conn:
    record = register_run(conn, body, principal, now=utc_now())
  return record
