"""Durable human stop plus separately acknowledged atomic rail enforcement."""

import os
from uuid import uuid4
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends

from activity import emit_activity
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.models import Contract, RunId, MandateStatus
from mandate_service import utc_now, version_record, transition, audit
from leash_shared.events import EventType
from principals import Principal, require_human, require_agent
from payment_operations import cancel_prepared

router = APIRouter(tags=["workflow control"])


def lock_user_authority(conn, user_id: str) -> None:
  conn.execute("SELECT id FROM leash_users WHERE id = %s FOR UPDATE", (user_id,))
  row = conn.execute(
    "SELECT stopped FROM user_workflow_controls WHERE user_id = %s", (user_id,)
  ).fetchone()
  if row and row["stopped"]:
    raise AuthorityError(
      409, "Shopping is stopped; existing authority cannot be resumed"
    )


class StopRequest(Contract):
  on: Literal[True]


def stop_rail(user_id: str) -> dict:
  token = os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()
  url = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
  if len(token) < 32 or not url:
    return {"status": "pending", "reason": "Rail enforcement is not configured"}
  try:
    with httpx.Client(base_url=url, timeout=3, follow_redirects=False) as client:
      response = client.post(
        "/internal/killswitch",
        headers={"Authorization": "Bearer " + token},
        json={"user_id": user_id, "on": True},
      )
    data = response.json()
    if (
      response.is_success
      and data.get("user_id") == user_id
      and data.get("killswitch_on") is True
      and type(data.get("unused_grants_revoked")) is int
      and data["unused_grants_revoked"] >= 0
    ):
      return {
        "status": "enforced",
        "unused_grants_revoked": data["unused_grants_revoked"],
      }
  except (httpx.HTTPError, ValueError, AttributeError):
    pass
  return {
    "status": "pending",
    "reason": "Rail did not acknowledge enforcement; retry this stop request",
  }


def stop_rail_run(user_id: str, run_id: str) -> dict:
  """Atomic unused-grant barrier for one run. Does not stop the account."""
  token = os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()
  url = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
  if len(token) < 32 or not url:
    return {"status": "pending", "reason": "Rail enforcement is not configured"}
  try:
    with httpx.Client(base_url=url, timeout=3, follow_redirects=False) as client:
      response = client.post(
        "/internal/run-stop",
        headers={"Authorization": "Bearer " + token},
        json={"user_id": user_id, "run_id": run_id},
      )
    data = response.json()
    if (
      response.is_success
      and data.get("user_id") == user_id
      and data.get("run_id") == run_id
      and data.get("run_stop_on") is True
      and type(data.get("unused_grants_revoked")) is int
      and data["unused_grants_revoked"] >= 0
    ):
      return {
        "status": "enforced",
        "unused_grants_revoked": data["unused_grants_revoked"],
      }
  except (httpx.HTTPError, ValueError, AttributeError):
    pass
  return {
    "status": "pending",
    "reason": "Rail did not acknowledge run stop; retry this stop request",
  }


def close_owned_cards(user_id):
  """Reconcile durable CLOSED intents. Historical PAUSE records remain intact."""
  token = os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()
  url = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
  with get_conn() as conn:
    operations = conn.execute(
      "SELECT * FROM card_control_operations WHERE user_id=%s AND requested_state='CLOSED' ORDER BY id", (user_id,)
    ).fetchall()
  confirmed = 0
  for operation in operations:
    if operation["outcome"] == "confirmed":
      confirmed += 1
      continue
    observed = None
    if len(token) >= 32 and url:
      try:
        with httpx.Client(base_url=url, timeout=3, follow_redirects=False) as client:
          response = client.post(
            "/internal/lithic/card-state",
            headers={"Authorization": "Bearer " + token},
            json={"card_token": operation["card_token"], "state": "CLOSED"},
          )
        data = response.json()
        if (
          response.is_success
          and data.get("provider") == "lithic_sandbox"
          and data.get("card_token") == operation["card_token"]
          and data.get("state") == "CLOSED"
        ):
          observed = data["state"]
      except (httpx.HTTPError, ValueError, AttributeError):
        pass
    with get_conn() as conn:
      # A late timeout cannot overwrite another retry's confirmed closure.
      conn.execute(
        """UPDATE card_control_operations SET outcome=%s,
        observed_state=%s,observed_at=%s WHERE id=%s AND outcome!='confirmed'""",
        ("confirmed" if observed else "unknown", observed, utc_now(), operation["id"]),
      )
      emit_activity(
        conn,
        user_id=user_id,
        event_type="card.control.outcome",
        data={
          "operation_id": operation["id"],
          "requested_state": "CLOSED",
          "outcome": "confirmed" if observed else "unknown",
          "observed_state": observed,
          "provider": "lithic_sandbox",
        },
        auth_user_id=_auth_id(conn, user_id),
      )
    if observed:
      confirmed += 1
  # Read committed state; another concurrent retry may have confirmed an outcome.
  with get_conn() as conn:
    row = conn.execute(
      "SELECT count(*) total,count(*) FILTER (WHERE outcome='confirmed' AND observed_state='CLOSED') confirmed FROM card_control_operations WHERE user_id=%s AND requested_state='CLOSED'",
      (user_id,),
    ).fetchone()
  return {
    "status": "not_required"
    if not row["total"]
    else "enforced"
    if row["confirmed"] == row["total"]
    else "pending",
    "total": row["total"],
    "confirmed": row["confirmed"],
  }


@router.post("/killswitch")
def stop_workflow(
  body: StopRequest, principal: Annotated[Principal, Depends(require_human)]
):
  now = utc_now()
  with get_conn() as conn:
    # Same first lock as approval/registration. Once committed, no new run or
    # confirmation can slip past the stop while the rail call is in flight.
    conn.execute(
      "SELECT id FROM leash_users WHERE id = %s FOR UPDATE", (principal.user_id,)
    )
    first_stop = conn.execute(
      """INSERT INTO user_workflow_controls (user_id, stopped, changed_at)
      VALUES (%s,true,%s) ON CONFLICT (user_id) DO UPDATE
      SET stopped=true,changed_at=EXCLUDED.changed_at
      WHERE NOT user_workflow_controls.stopped RETURNING user_id""",
      (principal.user_id, now),
    ).fetchone()
    heads = conn.execute(
      "SELECT * FROM mandate_heads WHERE user_id = %s ORDER BY id FOR UPDATE",
      (principal.user_id,),
    ).fetchall()
    revoked = 0
    for head in heads:
      record = version_record(conn, head["id"], head["current_version"], now=now)
      if record.status in {MandateStatus.ACTIVE, MandateStatus.PROPOSED}:
        record = record.model_copy(update={"status": MandateStatus.REVOKED})
        transition(conn, record, MandateStatus.REVOKED, now)
        audit(
          conn,
          EventType.MANDATE_REVOKED,
          record,
          now=now,
          extra={"source": "human_killswitch"},
        )
        revoked += 1
    conn.execute(
      """INSERT INTO run_cancellations (run_id,user_id,requested_at)
      SELECT id,user_id,%s FROM agent_runs WHERE user_id=%s ON CONFLICT DO NOTHING""",
      (now, principal.user_id),
    )
    cancel_prepared(conn, principal.user_id, reason="account_stopped")
    owned_cards = conn.execute(
      """SELECT c.card_token FROM lithic_cards c
          JOIN leash_users l ON l.auth_user_id=c.user_id WHERE l.id=%s
          UNION SELECT u.lithic_card_token AS card_token FROM users u
          JOIN leash_users l ON l.auth_user_id=u.id WHERE l.id=%s AND u.lithic_card_token IS NOT NULL""",
      (principal.user_id, principal.user_id),
    ).fetchall()
    for card in owned_cards:
      operation_id = "ctl_" + uuid4().hex
      created = conn.execute(
        """INSERT INTO card_control_operations
            (id,user_id,card_token,requested_state,requested_at) VALUES (%s,%s,%s,'CLOSED',%s)
            ON CONFLICT (user_id,card_token,requested_state) DO NOTHING RETURNING id""",
        (operation_id, principal.user_id, card["card_token"], now),
      ).fetchone()
      if created:
        emit_activity(
          conn,
          user_id=principal.user_id,
          event_type="card.control.requested",
          data={
            "operation_id": operation_id,
            "requested_state": "CLOSED",
            "provider": "lithic_sandbox",
          },
          auth_user_id=_auth_id(conn, principal.user_id),
        )
    if first_stop:
      emit_activity(
        conn,
        user_id=principal.user_id,
        event_type=EventType.KILLSWITCH_CHANGED.value,
        data={"on": True, "scope": "account", "stage": "requested", "mandates_revoked": revoked},
        auth_user_id=_auth_id(conn, principal.user_id),
      )
  rail = stop_rail(principal.user_id)
  cards = close_owned_cards(principal.user_id)
  with get_conn() as conn:
    if rail["status"] == "enforced":
      conn.execute(
        "UPDATE user_workflow_controls SET rail_enforced_at=%s WHERE user_id=%s",
        (utc_now(), principal.user_id),
      )
      conn.execute("""UPDATE run_executions SET rail_stopped_at=COALESCE(rail_stopped_at,now())
                      WHERE run_id IN (SELECT id FROM agent_runs WHERE user_id=%s)""", (principal.user_id,))
    emit_activity(
      conn,
      user_id=principal.user_id,
      event_type=EventType.KILLSWITCH_CHANGED.value,
      data={"on": True, "stage": "rail_outcome", **rail},
      auth_user_id=_auth_id(conn, principal.user_id),
    )
  return {
    "on": True,
    "status": "financially_stopped"
    if rail["status"] == "enforced" and cards["status"] != "pending"
    else "pending_enforcement",
    "mandates_revoked": revoked,
    "rail": rail,
    "run_cancellation": "requested",
    "graph_cancellation": "not_acknowledged",
    "provider_card_controls": cards,
    "previous_authorizations_reversed": False,
  }


def _auth_id(conn, user_id):
  row = conn.execute(
    "SELECT auth_user_id FROM leash_users WHERE id=%s", (user_id,)
  ).fetchone()
  return str(row["auth_user_id"]) if row["auth_user_id"] else None


@router.get("/killswitch")
def get_stop(principal: Annotated[Principal, Depends(require_human)]):
  with get_conn() as conn:
    row = conn.execute(
      "SELECT * FROM user_workflow_controls WHERE user_id=%s",
      (principal.user_id,),
    ).fetchone()
    cards = conn.execute(
      "SELECT count(*) total,count(*) FILTER (WHERE outcome='confirmed' AND observed_state='CLOSED') confirmed FROM card_control_operations WHERE user_id=%s AND requested_state='CLOSED'",
      (principal.user_id,),
    ).fetchone()
  return {
    "on": bool(row and row["stopped"]),
    "rail_enforced": bool(row and row["rail_enforced_at"]),
    "provider_controls_enforced": cards["confirmed"] == cards["total"],
  }


@router.get("/agent-runs/{run_id}/control")
def run_control(run_id: RunId, principal: Annotated[Principal, Depends(require_agent)]):
  with get_conn() as conn:
    run = conn.execute(
      "SELECT * FROM agent_runs WHERE id=%s AND user_id=%s AND agent_id=%s",
      (run_id, principal.user_id, principal.agent_id),
    ).fetchone()
    if run is None:
      raise AuthorityError(404, "Registered run not found")
    stopped = conn.execute(
      "SELECT stopped FROM user_workflow_controls WHERE user_id=%s",
      (principal.user_id,),
    ).fetchone()
    cancelled = conn.execute(
      "SELECT run_id FROM run_cancellations WHERE run_id=%s", (run_id,)
    ).fetchone()
    mandate = version_record(
      conn, run["mandate_id"], run["mandate_version"], now=utc_now()
    )
    head = conn.execute(
      "SELECT current_version FROM mandate_heads WHERE id=%s",
      (run["mandate_id"],),
    ).fetchone()
  allowed = (
    not cancelled
    and not (stopped and stopped["stopped"])
    and mandate.status == MandateStatus.ACTIVE
    and head["current_version"] == mandate.version
    and mandate.valid_from <= utc_now() < mandate.valid_until
  )
  return {
    "run_id": run_id,
    "cancel_requested": bool(cancelled),
    "authority_current": bool(allowed),
  }


def _owned_run(conn, run_id, user_id):
  run = conn.execute(
    "SELECT * FROM agent_runs WHERE id=%s AND user_id=%s", (run_id, user_id)
  ).fetchone()
  if run is None:
    raise AuthorityError(404, "Registered run not found")
  return run


def _run_stop_state(conn, run, *, rail: dict | None = None):
  cancelled = conn.execute(
    "SELECT requested_at FROM run_cancellations WHERE run_id=%s", (run["id"],)
  ).fetchone()
  # Run-scoped Graph executions record their own rail stop and Graph ack.
  execution = conn.execute("SELECT rail_stopped_at,graph_ack_at FROM run_executions WHERE run_id=%s", (run["id"],)).fetchone()
  enforced = bool(rail and rail.get("status") == "enforced") or bool(execution and execution["rail_stopped_at"])
  if not cancelled:
    financial = "not_requested"
    status = "not_requested"
  elif enforced:
    financial = "enforced"
    status = "enforced"
  else:
    financial = "pending_rail_ack"
    status = "pending_enforcement"
  return {
    "run_id": run["id"],
    "scope": "run",
    "cancel_requested": bool(cancelled),
    "requested_at": cancelled["requested_at"] if cancelled else None,
    "status": status,
    # Rail run-stop latches unused grants for this run_id; shared mandate intact.
    "financial_revocation": financial,
    "graph_cancellation": "acknowledged" if execution and execution["graph_ack_at"] else "not_acknowledged",
    "provider_card_controls": "not_required_local_rail" if execution else "pending_dedicated_card_binding" if cancelled else "not_requested",
    "previous_authorizations_reversed": False,
    "rail": rail,
  }


@router.get("/agent-runs")
def list_owned_runs(principal: Annotated[Principal, Depends(require_human)]):
  with get_conn() as conn:
    runs = conn.execute(
      "SELECT * FROM agent_runs WHERE user_id=%s ORDER BY record->>'created_at' DESC,id LIMIT 100",
      (principal.user_id,),
    ).fetchall()
    return {
      "runs": [
        {"id": run["id"], "mandate_id": run["mandate_id"],
         "agent_mode": run["registration"]["agent_mode"],
         "stop": _run_stop_state(conn, run)} for run in runs
      ],
      "limit": 100,
    }


@router.get("/agent-runs/{run_id}/stop")
def get_run_stop(run_id: RunId, principal: Annotated[Principal, Depends(require_human)]):
  with get_conn() as conn:
    return _run_stop_state(conn, _owned_run(conn, run_id, principal.user_id))


@router.post("/agent-runs/{run_id}/stop")
def stop_run(run_id: RunId, principal: Annotated[Principal, Depends(require_human)]):
  with get_conn() as conn:
    # Registration/approval/account stop take this same first lock. This
    # operation never revokes a shared mandate or another run's permissions.
    conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
    run = _owned_run(conn, run_id, principal.user_id)
    created = conn.execute(
      """INSERT INTO run_cancellations (run_id,user_id,requested_at)
      VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING run_id""",
      (run_id, principal.user_id, utc_now()),
    ).fetchone()
    cancel_prepared(conn, principal.user_id, run_id=run_id, reason="run_stopped")
    if created:
      emit_activity(
        conn, user_id=principal.user_id, event_type="run.stop.requested",
        data={"run_id": run_id, "scope": "run", "financial_revocation": "pending_rail_ack",
              "graph_cancellation": "not_acknowledged"},
        auth_user_id=_auth_id(conn, principal.user_id),
      )
  # Outside the SQL lock: Valkey run latch + unused grant revoke for this run only.
  rail = stop_rail_run(principal.user_id, run_id)
  with get_conn() as conn:
    if rail.get("status") == "enforced":
      conn.execute("UPDATE run_executions SET rail_stopped_at=COALESCE(rail_stopped_at,now()) WHERE run_id=%s", (run_id,))
      emit_activity(conn, user_id=principal.user_id, event_type="run.stop.enforced",
                    data={"run_id": run_id, "scope": "run", "financial_revocation": "enforced"},
                    auth_user_id=_auth_id(conn, principal.user_id))
    return _run_stop_state(conn, _owned_run(conn, run_id, principal.user_id), rail=rail)
