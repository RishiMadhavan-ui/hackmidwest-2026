"""Authenticated, bounded agent evidence intake; reports never create authority."""

import json
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from audit_store import append_event
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.events import agent_report_event, parse_provenance
from principals import Principal, require_agent

router = APIRouter(tags=["provenance"])
MAX_EVENT_BYTES = 128 * 1024


@router.post("/provenance", status_code=201)
async def post_provenance(
    request: Request, principal: Annotated[Principal, Depends(require_agent)]
):
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_EVENT_BYTES:
            raise AuthorityError(413, "Provenance event exceeds the size limit")
    try:
        report = parse_provenance(json.loads(payload))
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise AuthorityError(422, "Invalid provenance fields or values") from None
    # Run ownership is required even for late-arriving evidence after revocation:
    # revocation stops authority, not delivery of the evidence explaining it.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(store_report, report, principal)


def store_report(report, principal: Principal):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = %s AND user_id = %s AND agent_id = %s",
            (report.run_id, principal.user_id, principal.agent_id),
        ).fetchone()
        if row is None:
            raise AuthorityError(404, "Registered agent run not found")
        try:
            event = agent_report_event(
                report,
                user_id=principal.user_id,
                authenticated_agent_id=principal.agent_id,
                authorized_run_id=row["id"],
                authorized_agent_mode=row["record"]["agent_mode"],
                configured_snapshot_bucket=os.getenv("OBJ_BUCKET") or None,
            )
        except ValueError:
            raise AuthorityError(
                422, "Provenance identity, mode or snapshot binding is invalid"
            ) from None
        if not append_event(conn, event.model_dump(mode="json"), duplicate_ok=True):
            # Return 409 only for a duplicate belonging to this caller/run. A guessed
            # event ID cannot be used to probe another owner's persisted event.
            old = conn.execute(
                "SELECT user_id, record FROM audit_events WHERE event_id = %s",
                (event.event_id,),
            ).fetchone()
            if (
                old["user_id"] != principal.user_id
                or old["record"].get("data", {}).get("run_id") != report.run_id
            ):
                raise AuthorityError(
                    422, "Event identifier conflicts with another record"
                )
            if old["record"] != event.model_dump(mode="json"):
                raise AuthorityError(
                    422, "Event identifier conflicts with its original payload"
                )
            raise AuthorityError(409, "Event already stored")
    return {"event_id": event.event_id, "status": "stored"}
