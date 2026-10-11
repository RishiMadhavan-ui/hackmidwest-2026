"""Bounded agent execution observations into existing append-only history/SSE."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, JsonValue, model_validator
from starlette.concurrency import run_in_threadpool

from audit_store import append_event
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.events import AgentReportedEvent, AuditEvent, EventType, sanitize_event_data
from principals import Principal, require_agent

router = APIRouter(tags=["workflow evidence"])
FIELDS = {
  "graph.started": set(), "graph.stopped": {"outcome","reason"}, "graph.failed": {"outcome"},
  "lease.claimed": {"worker_id","generation"}, "node.started": {"node","attempt"},
  "node.completed": {"node","attempt","outcome"}, "edge.traversed": {"source","target","attempt"},
  "verification.result": {"attempt","status","reasons","payment_id"},
  "candidate.quarantined": {"attempt","exclusions"},
  "recovery.started": {"attempt","reasons","exclusions"}, "run.terminal": {"outcome","attempt"},
  "investigation.started": {"attempt","source_hashes","payment_id"},
  "investigation.unavailable": {"reason"},
  "investigation.completed": {"authority","attempt","recommendation","intent_match","injection_suspected",
                              "source_urls","source_hashes","payment_id"},
  "payment.started": {"payment_id","checkout_id"}, "payment.authorized": {"payment_id"},
}
for phase in ("inference.started", "inference.completed", "inference.failed"):
  FIELDS[phase] = {"inference_id","role","provider","model","execution","duration_ms","error"}


class WorkflowReport(AgentReportedEvent):
  type: Literal["agent.step"]
  schema_version: Literal[1]
  phase: str = Field(max_length=50)
  data: dict[str, JsonValue]

  @model_validator(mode="after")
  def bounded_metadata(self):
    if self.phase not in FIELDS or set(self.data) - FIELDS[self.phase]:
      raise ValueError("Unknown workflow phase or fields")
    def check(value, depth=0):
      if depth > 3:
        raise ValueError("Nested metadata is not allowed")
      if isinstance(value, str) and len(value) > 1024:
        raise ValueError("Workflow text exceeds limit")
      if isinstance(value, list):
        if len(value) > 30:
          raise ValueError("Metadata list exceeds limit")
        for item in value:
          check(item, depth+1)
      if isinstance(value, dict):
        for item in value.values():
          check(item, depth+1)
    check(self.data)
    exclusions = self.data.get("exclusions", {})
    if not isinstance(exclusions, dict) or set(exclusions) - {"skus","checkouts","source_hashes","source_urls"}:
      raise ValueError("Invalid exclusions")
    if sanitize_event_data(self.data) != self.data:
      raise ValueError("Sensitive metadata is not accepted")
    return self


@router.post("/workflow-events", status_code=201)
async def intake(request: Request, principal: Annotated[Principal, Depends(require_agent)]):
  body = bytearray()
  async for chunk in request.stream():
    body.extend(chunk)
    if len(body) > 32768:
      raise AuthorityError(413, "Workflow event exceeds size limit")
  try:
    report = WorkflowReport.model_validate_json(body)
  except (ValueError, RecursionError):
    raise AuthorityError(422, "Invalid workflow metadata") from None
  return await run_in_threadpool(store, report, principal)


def store(report, principal):
  if principal.delegated_run and principal.delegated_run != report.run_id:
    raise AuthorityError(404, "Registered run not found")
  with get_conn() as conn:
    run = conn.execute("SELECT * FROM agent_runs WHERE id=%s AND user_id=%s AND agent_id=%s",
      (report.run_id, principal.user_id, principal.agent_id)).fetchone()
    if not run:
      raise AuthorityError(404, "Registered run not found")
    if report.agent_id != principal.agent_id or report.agent_mode != run["registration"]["agent_mode"]:
      raise AuthorityError(422, "Workflow identity or mode mismatch")
    record = AuditEvent(event_id=report.event_id, type=EventType.AGENT_STEP, at=report.timestamp,
      user_id=principal.user_id, data={"run_id": report.run_id, "agent_id": report.agent_id,
      "agent_mode": report.agent_mode, "schema_version": 1, "phase": report.phase,
      "trust_classification": "agent_observation", "reported": report.data}).model_dump(mode="json")
    if not append_event(conn, record, duplicate_ok=True):
      old = conn.execute("SELECT record FROM audit_events WHERE event_id=%s", (report.event_id,)).fetchone()
      if old["record"] != record:
        raise AuthorityError(422, "Event identifier conflicts with original evidence")
      raise AuthorityError(409, "Event already stored")
  return {"event_id": report.event_id, "status": "stored"}
