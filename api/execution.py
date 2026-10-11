"""Human launches, single-owner durable leases and audience-bound opaque scopes."""

import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field, StrictInt
from psycopg.types.json import Jsonb

from activity import emit_activity
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.models import Contract, AgentRunRegistration, MandateId, RunId, Sha256
from mandate_service import current_mandate, register_run, utc_now
from principals import Principal, require_agent, require_human

router = APIRouter(tags=["execution"])
LEASE_SECONDS = 10
ACTIONS = {
  "mcp-leash": {"list_mandates", "request_payment", "check_status"},
  "mcp-store": {"browse", "create_checkout", "complete_checkout"},
}


def digest(value):
  return hashlib.sha256(value.encode()).hexdigest()


def enabled():
  if os.getenv("LEASH_EXECUTION_ENABLED") != "1":
    raise AuthorityError(503, "Purchase execution is disabled")


def rail(method, path, body=None):
  url, token = os.getenv("WEBHOOK_URL", "").rstrip("/"), os.getenv("WEBHOOK_INTERNAL_TOKEN", "")
  if not url or len(token) < 32:
    raise AuthorityError(503, "Execution rail is not configured")
  try:
    with httpx.Client(base_url=url, timeout=3, follow_redirects=False) as client:
      response = client.request(method, path, json=body, headers={"Authorization": "Bearer " + token})
    if not response.is_success:
      raise AuthorityError(503, "Execution rail did not acknowledge the operation")
    result = response.json()
    if not isinstance(result, dict):
      raise ValueError()
    return result
  except (httpx.HTTPError, ValueError):
    raise AuthorityError(503, "Execution rail unavailable; outcome requires reconciliation") from None


def event(conn, run, phase, **data):
  row = conn.execute("SELECT auth_user_id FROM leash_users WHERE id=%s", (run["user_id"],)).fetchone()
  emit_activity(conn, user_id=run["user_id"], event_type="execution." + phase,
    auth_user_id=str(row["auth_user_id"]) if row["auth_user_id"] else None,
    data={"run_id": run["id"], **data})


def locked(conn, run_id, principal=None, *, current=True):
  run = conn.execute("SELECT * FROM agent_runs WHERE id=%s", (run_id,)).fetchone()
  if not run or (principal and (run["user_id"] != principal.user_id or
      (principal.role == "agent" and run["agent_id"] != principal.agent_id))):
    raise AuthorityError(404, "Execution run not found")
  conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (run["user_id"],))
  lease = conn.execute("SELECT * FROM run_executions WHERE run_id=%s FOR UPDATE", (run_id,)).fetchone()
  if not lease:
    raise AuthorityError(409, "A human launch is required")
  if current:
    p = Principal("agent", run["user_id"], run["agent_id"], (run["registration"]["agent_mode"],))
    mandate = current_mandate(conn, run["mandate_id"], p, now=utc_now(), lock=True)
    stopped = conn.execute("SELECT stopped FROM user_workflow_controls WHERE user_id=%s", (run["user_id"],)).fetchone()
    if (conn.execute("SELECT 1 FROM run_cancellations WHERE run_id=%s", (run_id,)).fetchone()
        or (stopped and stopped["stopped"]) or mandate.status.value != "active"
        or not mandate.valid_from <= utc_now() < mandate.valid_until
        or mandate.version != run["mandate_version"] or mandate.canonical_payload_hash != run["record"]["mandate_hash"]
        or lease["deadline"] <= utc_now() or lease["state"] == "terminal"):
      raise AuthorityError(409, "Execution authority is no longer current")
  return run, lease


def financial_state(conn, run_id):
  rows = conn.execute("SELECT state FROM payment_operations WHERE run_id=%s", (run_id,)).fetchall()
  states = {r["state"] for r in rows}
  if "authorized" in states:
    return "authorized"
  if states & {"authorizing", "reconciling", "activating"}:
    return "reconciling"
  if "ready" in states:
    return "reserved"
  return "unspent"


def projection(conn, run, lease):
  return {"protocol": "execution-v1", "run_id": run["id"], "worker_id": lease["worker_id"],
    "generation": lease["generation"], "authority_current": True, "cancel_requested": False,
    "human_launch_verified": True, "financial_state": financial_state(conn, run["id"]),
    "lease_seconds": max(0, (lease["lease_until"] - utc_now()).total_seconds()),
    "mcp_scope_enforced": True}


class Launch(Contract):
  mandate_id: MandateId
  version: StrictInt
  canonical_payload_hash: Sha256
  confirmed: Literal[True]
  start_url: str | None = Field(default=None, max_length=1000)


@router.post("/agent-runs/launch", status_code=201)
def launch(body: Launch, principal: Annotated[Principal, Depends(require_human)]):
  enabled()
  secret, run_id = secrets.token_urlsafe(32), "run_" + uuid4().hex
  with get_conn() as conn:
    conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
    mandate = current_mandate(conn, body.mandate_id, principal, now=utc_now(), lock=True)
    if (body.version, body.canonical_payload_hash) != (mandate.version, mandate.canonical_payload_hash):
      raise AuthorityError(409, "Confirm the current mandate version and hash")
    agent = conn.execute("SELECT * FROM leash_agents WHERE id=%s AND user_id=%s AND enabled", (mandate.agent_id, principal.user_id)).fetchone()
    if not agent or len(agent["allowed_modes"]) != 1:
      raise AuthorityError(409, "Mandate agent has not been provisioned")
    if conn.execute("""SELECT 1 FROM payment_operations WHERE user_id=%s AND mandate_id=%s
        AND state IN ('prepared','activating','ready','authorizing','reconciling','authorized')""",
        (principal.user_id, mandate.id)).fetchone():
      raise AuthorityError(409, "Existing payment authority or outcome prevents a new launch")
    if conn.execute("""SELECT 1 FROM run_executions e JOIN agent_runs r ON r.id=e.run_id
        WHERE r.user_id=%s AND r.mandate_id=%s AND e.state!='terminal' AND e.deadline>now()
        AND NOT EXISTS (SELECT 1 FROM run_cancellations c WHERE c.run_id=e.run_id)""",
        (principal.user_id, mandate.id)).fetchone():
      raise AuthorityError(409, "An active launch already owns this mandate")
    mode = agent["allowed_modes"][0]
    run = register_run(conn, AgentRunRegistration(id=run_id, mandate_id=mandate.id, agent_mode=mode),
      Principal("agent", principal.user_id, agent["id"], (mode,)), now=utc_now())
    conn.execute("INSERT INTO run_executions(run_id,launch_hash,deadline) VALUES (%s,%s,%s)",
      (run_id, digest(secret), min(mandate.valid_until, utc_now() + timedelta(seconds=180))))
    event(conn, {"id": run_id, "user_id": principal.user_id}, "launched", mandate_id=mandate.id)
  return {"run_id": run_id, "launch_id": secret, "mandate_id": mandate.id,
    "task": mandate.description, "agent_mode": run.agent_mode, "start_url": body.start_url}


class Claim(Contract):
  protocol: Literal["execution-v1"]
  worker_id: str = Field(pattern=r"^worker_[a-f0-9]{32}$")
  launch_id: str = Field(min_length=32, max_length=128)


class Binding(Contract):
  worker_id: str = Field(min_length=1, max_length=128)
  generation: StrictInt = Field(ge=1)


def match_worker(lease, body, *, live=True):
  if (lease["worker_id"], lease["generation"]) != (body.worker_id, body.generation):
    raise AuthorityError(409, "Stale execution worker")
  if live and (lease["lease_until"] is None or lease["lease_until"] <= utc_now()):
    raise AuthorityError(409, "Execution lease expired")


def renew_rail(run, lease, until):
  reply = rail("POST", "/internal/execution/lease", {
    "run_id": run["id"], "user_id": run["user_id"], "generation": lease["generation"],
    "epoch": lease["rail_epoch"], "lease_until": until.isoformat()})
  if reply.get("epoch") != lease["rail_epoch"] or reply.get("run_id") != run["id"]:
    raise AuthorityError(503, "Rail lease acknowledgment mismatch")


@router.post("/agent-runs/{run_id}/execution/claim")
def claim(run_id: RunId, body: Claim, principal: Annotated[Principal, Depends(require_agent)]):
  enabled()
  tokens = {aud: secrets.token_urlsafe(32) for aud in ACTIONS}
  with get_conn() as conn:
    run, lease = locked(conn, run_id, principal)
    if lease["claimed_at"] or not hmac.compare_digest(lease["launch_hash"], digest(body.launch_id)):
      raise AuthorityError(409, "Launch is invalid or already consumed")
    until = min(lease["deadline"], utc_now() + timedelta(seconds=LEASE_SECONDS))
    epoch = rail("GET", "/internal/execution/epoch")["epoch"]
    lease.update(worker_id=body.worker_id, rail_epoch=epoch, lease_until=until)
    renew_rail(run, lease, until)
    conn.execute("""UPDATE run_executions SET worker_id=%s,claimed_at=now(),lease_until=%s,
      rail_epoch=%s,state='running',leash_token_hash=%s,store_token_hash=%s WHERE run_id=%s""",
      (body.worker_id, until, epoch, digest(tokens["mcp-leash"]), digest(tokens["mcp-store"]), run_id))
    event(conn, run, "claimed", generation=lease["generation"])
    return {**projection(conn, run, lease), "scope_tokens": tokens}


@router.post("/agent-runs/{run_id}/execution/heartbeat")
def heartbeat(run_id: RunId, body: Binding, principal: Annotated[Principal, Depends(require_agent)]):
  with get_conn() as conn:
    run, lease = locked(conn, run_id, principal)
    match_worker(lease, body)
    until = min(lease["deadline"], utc_now() + timedelta(seconds=LEASE_SECONDS))
    renew_rail(run, lease, until)
    # Network time cannot resurrect a worker whose old lease elapsed.
    match_worker(lease, body)
    conn.execute("UPDATE run_executions SET lease_until=%s WHERE run_id=%s", (until, run_id))
    lease["lease_until"] = until
    return projection(conn, run, lease)


class Progress(Contract):
  attempt: StrictInt = Field(ge=0, le=3)
  node: Literal["authority","shopping","verification","investigation","recovery","payment","terminal"]
  outcome: Literal["running","blocked","authorized","reconciling","declined","stopped","cancelled","no_candidate","failed"]
  exclusions: dict[str, list[str]]
  reasons: list[str] = Field(max_length=30)
  checkout_id: str | None = Field(default=None, max_length=128)
  payment_id: str | None = Field(default=None, max_length=128)
  financial_attempted: bool
  finished: bool = False


class Checkpoint(Binding):
  progress: Progress


@router.post("/agent-runs/{run_id}/execution/checkpoint")
def checkpoint(run_id: RunId, body: Checkpoint, principal: Annotated[Principal, Depends(require_agent)]):
  data = body.progress.model_dump(mode="json")
  from leash_shared.models import canonical_json
  if len(canonical_json(data)) > 16000:
    raise AuthorityError(422, "Checkpoint is too large")
  with get_conn() as conn:
    run, lease = locked(conn, run_id, principal, current=False)
    match_worker(lease, body, live=False)
    old = lease["progress"]
    if data["attempt"] < old.get("attempt", 0):
      raise AuthorityError(409, "Execution attempt cannot be reset")
    if lease["state"] == "terminal" and data != old:
      raise AuthorityError(409, "Terminal checkpoint is immutable")
    terminal = data["finished"] and data["outcome"] != "running"
    if not terminal:
      locked(conn, run_id, principal)
      match_worker(lease, body)
    # This is evidence only. No agent checkpoint writes payment outcomes.
    conn.execute("""UPDATE run_executions SET progress=%s,state=%s,
      graph_ack_at=CASE WHEN %s THEN coalesce(graph_ack_at,now()) ELSE graph_ack_at END WHERE run_id=%s""",
      (Jsonb(data), "terminal" if terminal else "running", terminal, run_id))
    if terminal and lease["state"] != "terminal":
      event(conn, run, "worker_finished", reported_outcome=data["outcome"])
  return {"status": "stored"}


def validate_scope(conn, headers, audience, action, *, principal=None, live=True):
  token = headers.get("x-leash-execution-token", "")
  run_id = headers.get("x-leash-run-id", "")
  if audience not in ACTIONS or action not in ACTIONS[audience] or not 32 <= len(token) <= 128:
    raise AuthorityError(403, "Run-scoped tool credential required")
  run, lease = locked(conn, run_id, principal, current=live)
  expected = lease["leash_token_hash" if audience == "mcp-leash" else "store_token_hash"]
  if not expected or not hmac.compare_digest(expected, digest(token)):
    raise AuthorityError(403, "Tool credential audience or binding mismatch")
  try:
    binding = Binding(worker_id=headers.get("x-leash-worker-id", ""), generation=int(headers.get("x-leash-generation", "0")))
  except ValueError:
    raise AuthorityError(403, "Invalid execution binding") from None
  match_worker(lease, binding, live=live)
  if live and action in {"browse","create_checkout","request_payment"} and financial_state(conn, run_id) != "unspent":
    raise AuthorityError(409, "Financial reservation or uncertainty prevents another candidate")
  return run, lease


class ToolScope(Contract):
  audience: Literal["mcp-leash","mcp-store"]
  action: str = Field(max_length=40)


@router.post("/execution/authorize")
def authorize_scope(body: ToolScope, request: Request):
  with get_conn() as conn:
    run, lease = validate_scope(conn, request.headers, body.audience, body.action,
      live=body.action != "check_status")
    return {"run_id": run["id"], "mandate_id": run["mandate_id"], "user_id": run["user_id"],
      "generation": lease["generation"], "agent_id": run["agent_id"],
      "agent_mode": run["registration"]["agent_mode"]}
