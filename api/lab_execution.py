"""Explicit human-confirmed demo authority; genuine Graph on the local rail."""

import os
from typing import Literal

import httpx
from pydantic import Field, StrictBool, StrictInt

from attack_lab import Operator, EmptyRequest, owned, budget, server_enabled, record, router, outstanding_runs
from authority_errors import AuthorityError
from db import get_conn
from execution import Launch, launch, worker_credential
from leash_shared.models import MandateId, Sha256, MandateProposal, MandateStatus
from mandate_service import propose, approve, utc_now, list_mandates, revoke
from principals import Principal, bind_agent


class LabDraft(EmptyRequest):
  scenario: Literal["legitimate_charger", "signature_attack"]
  mode: Literal["live", "scripted"] = "live"


class LabStart(EmptyRequest):
  mandate_id: MandateId
  version: StrictInt = Field(ge=1)
  canonical_payload_hash: Sha256
  confirmed: StrictBool


def configured():
  return (os.getenv("LEASH_EXECUTION_ENABLED") == "1"
          and bool(os.getenv("AGENTS_URL")) and len(os.getenv("AGENTS_SERVICE_TOKEN", "")) >= 32
          and bool(os.getenv("STORE_URL")) and bool(os.getenv("WEBHOOK_URL")))


def enabled_namespace(conn, namespace_id, principal, *, lock=False):
  row = owned(conn, namespace_id, principal, lock=lock)
  if not server_enabled() or not row["enabled"]:
    raise AuthorityError(403, "Attack Lab execution is disabled")
  if not configured():
    raise AuthorityError(503, "Isolated local-rail Graph execution is not configured")
  return row


@router.post("/namespaces/{namespace_id}/draft", status_code=201)
@router.post("/namespaces/{namespace_id}/scenarios", status_code=201)
def draft(namespace_id: str, body: LabDraft, principal: Operator):
  from datetime import timedelta
  from uuid import uuid4
  import secrets
  with get_conn() as conn:
    row = enabled_namespace(conn, namespace_id, principal, lock=True)
    budget(conn, principal, now=utc_now())
    aid = "agt_lab_" + uuid4().hex
    bind_agent(conn, user_id=row["demo_user_id"], agent_id=aid,
               token=secrets.token_urlsafe(48), modes=(body.mode,))
    proposal = MandateProposal(description="Buy a USB-C laptop charger for under $40. No subscriptions.",
      category="laptop_charger", max_cents=3999, currency="USD", max_quantity=1, maximum_purchases=1,
      allow_subscription=False, allow_recurring=False,
      product_constraints=[{"name":"connector", "operator":"equals", "value":"USB-C"}],
      merchant_allowlist=["mer_volt_supply"], valid_until=utc_now()+timedelta(minutes=15))
    mandate = propose(conn, proposal, Principal("agent", row["demo_user_id"], aid, (body.mode,)), now=utc_now())
    conn.execute("INSERT INTO attack_lab_mandates(mandate_id,namespace_id,scenario,mode) VALUES (%s,%s,%s,%s)",
                 (mandate.id, namespace_id, body.scenario, body.mode))
    record(conn, principal, "draft.created", {"namespace_id": namespace_id, "mandate_id": mandate.id,
           "scenario": body.scenario, "mode": body.mode, "requires_confirmation": True}, now=utc_now())
    return {"mandate": mandate.model_dump(mode="json"), "scenario": body.scenario, "mode": body.mode,
            "rail": "local_payment_rail_simulator", "requires_confirmation": True}


@router.post("/namespaces/{namespace_id}/execute", status_code=202)
def execute(namespace_id: str, body: LabStart, principal: Operator):
  if body.confirmed is not True:
    raise AuthorityError(422, "Explicit confirmation of these exact demo terms is required")
  from datetime import timedelta
  with get_conn() as conn:
    row = enabled_namespace(conn, namespace_id, principal)
    # Survives approval's commit and launch's separate transaction. The next
    # request sees this run before it can launch another scenario.
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", ("lab-execute:"+namespace_id,))
    row = enabled_namespace(conn, namespace_id, principal, lock=True)
    binding = conn.execute("SELECT * FROM attack_lab_mandates WHERE mandate_id=%s AND namespace_id=%s",
                           (body.mandate_id, namespace_id)).fetchone()
    if not binding:
      raise AuthorityError(404, "Isolated demo mandate not found")
    if conn.execute("""SELECT 1 FROM attack_lab_runs l JOIN run_executions e USING(run_id)
      WHERE l.namespace_id=%s AND e.state!='terminal' AND e.deadline>now()""", (namespace_id,)).fetchone():
      raise AuthorityError(409, "One active scenario is permitted per workspace")
    if conn.execute("""SELECT 1 FROM payment_operations p JOIN attack_lab_runs l USING(run_id)
      WHERE l.namespace_id=%s AND p.state IN ('prepared','activating','ready','authorizing','reconciling')""", (namespace_id,)).fetchone():
      raise AuthorityError(409, "A prior demo outcome must be reconciled before another scenario")
    budget(conn, principal, now=utc_now())
    demo = Principal("human", row["demo_user_id"])
    mandate = approve(conn, body.mandate_id, demo, version=body.version,
                      content_hash=body.canonical_payload_hash, now=utc_now())
    conn.commit()
    launched = launch(Launch(mandate_id=mandate.id, version=mandate.version,
      canonical_payload_hash=mandate.canonical_payload_hash, confirmed=True), demo)
    deadline = utc_now()+timedelta(seconds=120)
    conn.execute("UPDATE run_executions SET deadline=LEAST(deadline,%s) WHERE run_id=%s", (deadline, launched["run_id"]))
    conn.execute("INSERT INTO attack_lab_runs(run_id,namespace_id,scenario,expires_at) VALUES (%s,%s,%s,%s)",
                 (launched["run_id"], namespace_id, binding["scenario"], deadline))
    conn.commit()
  payload = {"task": mandate.description, "mandate_id": mandate.id,
    "run_id": launched["run_id"], "launch_id": launched["launch_id"], "agent_mode": binding["mode"],
    "start_url": os.environ["STORE_URL"].rstrip("/")+"/products/chg-65w", "lab_execution": True,
    **worker_credential(launched["run_id"], demo)}
  if binding["mode"] == "scripted":
    payload.update(sku="SUB-CARE-MO" if binding["scenario"] == "signature_attack" else "CHG-65W",
                   claim_sku="CHG-65W", recovery_sku="CHG-65W-SAFE")
  try:
    with httpx.Client(timeout=10, follow_redirects=False) as client:
      result = client.post(os.environ["AGENTS_URL"].rstrip("/")+"/runs", json=payload,
                           headers={"Authorization": "Bearer "+os.environ["AGENTS_SERVICE_TOKEN"]})
    accepted = result.is_success and result.json().get("run_id") == launched["run_id"]
  except (httpx.HTTPError, ValueError):
    accepted = False
  # A timeout never starts a second run or buys a replacement. The same durable
  # run remains inspectable and stoppable until its hard deadline expires.
  return {"run_id": launched["run_id"], "status": "queued" if accepted else "dispatch_unverified",
          "mode": binding["mode"], "rail": "local_payment_rail_simulator", "namespace_id": namespace_id}


@router.get("/namespaces/{namespace_id}/history")
def history(namespace_id: str, principal: Operator):
  from purchase_history import summary
  with get_conn() as conn:
    row = owned(conn, namespace_id, principal)
    attempts = conn.execute("""SELECT o.*,p.record FROM payment_operations o
      LEFT JOIN payment_attempts p ON p.id=o.id WHERE o.user_id=%s ORDER BY o.created_at DESC LIMIT 50""",
      (row["demo_user_id"],)).fetchall()
    runs = conn.execute("""SELECT l.run_id,l.scenario,e.state,e.progress,e.deadline,
      e.rail_stopped_at,e.graph_ack_at FROM attack_lab_runs l JOIN run_executions e USING(run_id)
      WHERE l.namespace_id=%s ORDER BY l.created_at DESC LIMIT 20""", (namespace_id,)).fetchall()
    return {"attempts": [summary(item, conn) for item in attempts], "runs": runs,
            "rail": "local_payment_rail_simulator", "cleanup": "scopes_expire_120s_history_retained"}


@router.post("/namespaces/{namespace_id}/runs/{run_id}/stop")
def stop_scenario(namespace_id: str, run_id: str, body: EmptyRequest, principal: Operator):
  from workflow_control import stop_run
  with get_conn() as conn:
    row = owned(conn, namespace_id, principal)
    if not conn.execute("SELECT 1 FROM attack_lab_runs WHERE namespace_id=%s AND run_id=%s",
                        (namespace_id,run_id)).fetchone():
      raise AuthorityError(404,"Isolated scenario run not found")
  # Safety controls remain callable after enable flags change. They only
  # revoke, and cannot create a new scenario or spending permission.
  return stop_run(run_id,Principal("human",row["demo_user_id"]))


@router.post("/namespaces/{namespace_id}/cleanup")
@router.post("/namespaces/{namespace_id}/reset")
def cleanup(namespace_id: str, body: EmptyRequest, principal: Operator):
  from workflow_control import stop_run
  from purchase_execution import reconcile
  with get_conn() as conn:
    row = owned(conn, namespace_id, principal, lock=True)
    budget(conn, principal, now=utc_now())
    conn.execute("UPDATE attack_lab_namespaces SET enabled=false,revision=revision+1,updated_at=now() WHERE id=%s", (namespace_id,))
    demo = Principal("human", row["demo_user_id"])
    mandates = list_mandates(conn, demo, status=None, now=utc_now())
    for mandate in mandates:
      if mandate.status in {MandateStatus.ACTIVE, MandateStatus.PROPOSED}:
        revoke(conn, mandate.id, demo, version=mandate.version, content_hash=mandate.canonical_payload_hash, now=utc_now())
    runs = outstanding_runs(conn, namespace_id)
  outcomes = [stop_run(item["run_id"], demo) for item in runs]
  with get_conn() as conn:
    conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (demo.user_id,))
    pending = conn.execute("SELECT * FROM payment_operations WHERE user_id=%s AND state IN ('activating','ready','authorizing','reconciling') ORDER BY id LIMIT 20 FOR UPDATE", (demo.user_id,)).fetchall()
    for operation in pending:
      try:
        reconcile(conn, operation)
      except AuthorityError:
        pass
    record(conn, principal, "cleanup.requested", {"namespace_id": namespace_id, "history_retained": True}, now=utc_now())
  return {"namespace_id": namespace_id, "enabled": False, "stops": outcomes,
          "history_retained": True, "previous_authorizations_reversed": False}
