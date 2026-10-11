"""Service-authenticated delivery of sanitized run-bound observations only."""

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from authority_errors import AuthorityError
from db import get_conn
from leash_shared.events import parse_provenance
from principals import Credentials, Principal, credential_token

router = APIRouter(tags=["internal-evidence"])


def service_auth(credentials: Credentials):
  token = os.getenv("AGENTS_SERVICE_TOKEN", "")
  if len(token) < 32 or not hmac.compare_digest(token, credential_token(credentials)):
    raise AuthorityError(401, "Invalid evidence service credential")


def store_report(body):
  from provenance_routes import store_report as provenance_store
  from workflow_events import WorkflowReport, store as workflow_store
  try:
    report = WorkflowReport.model_validate(body) if body.get("type") == "agent.step" else parse_provenance(body)
  except (ValueError, ValidationError, TypeError, AttributeError):
    raise AuthorityError(422, "Invalid run observation") from None
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM agent_runs WHERE id=%s AND agent_id=%s",
                       (report.run_id, report.agent_id)).fetchone()
    if not row:
      raise AuthorityError(404, "Registered run not found")
    if report.agent_mode != row["registration"]["agent_mode"]:
      raise AuthorityError(422, "Observation mode mismatch")
    principal = Principal("agent", row["user_id"], row["agent_id"], (report.agent_mode,), row["id"])
  return workflow_store(report, principal) if isinstance(report, WorkflowReport) else provenance_store(report, principal)


@router.post("/internal/agent-events", status_code=201, dependencies=[Depends(service_auth)])
async def intake(request: Request):
  import json
  raw = bytearray()
  async for chunk in request.stream():
    raw.extend(chunk)
    if len(raw) > 128 * 1024:
      raise AuthorityError(413, "Observation exceeds size limit")
  try:
    body = json.loads(raw)
  except (ValueError, RecursionError):
    raise AuthorityError(422, "Invalid observation") from None
  return await run_in_threadpool(store_report, body)
