"""Durable human stop plus separately acknowledged atomic rail enforcement."""

import os
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
        conn.execute(
            """INSERT INTO user_workflow_controls (user_id, stopped, changed_at)
      VALUES (%s,true,%s) ON CONFLICT (user_id) DO UPDATE SET stopped=true""",
            (principal.user_id, now),
        )
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
        emit_activity(
            conn,
            user_id=principal.user_id,
            event_type=EventType.KILLSWITCH_CHANGED.value,
            data={"on": True, "stage": "requested", "mandates_revoked": revoked},
            auth_user_id=_auth_id(conn, principal.user_id),
        )
    rail = stop_rail(principal.user_id)
    with get_conn() as conn:
        if rail["status"] == "enforced":
            conn.execute(
                "UPDATE user_workflow_controls SET rail_enforced_at=%s WHERE user_id=%s",
                (utc_now(), principal.user_id),
            )
        emit_activity(
            conn,
            user_id=principal.user_id,
            event_type=EventType.KILLSWITCH_CHANGED.value,
            data={"on": True, "stage": "rail_outcome", **rail},
            auth_user_id=_auth_id(conn, principal.user_id),
        )
    return {
        "on": True,
        "status": "stopped" if rail["status"] == "enforced" else "pending_enforcement",
        "mandates_revoked": revoked,
        "rail": rail,
        "run_cancellation": "requested",
        "provider_card_controls": "not_implemented",
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
    return {
        "on": bool(row and row["stopped"]),
        "rail_enforced": bool(row and row["rail_enforced_at"]),
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
