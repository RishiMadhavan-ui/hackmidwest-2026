"""User-scoped activity history and SSE stream over durable audit_events.

Writes go through the same append-only audit_events table as mandate authority
events so Mission Control / R06 can later fan out from one source. Account
lifecycle types (account.*) are stored as sanitized envelopes; shared EventType
members (card.issued, payment.*, guardian.*, etc.) validate via AuditEvent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from db import get_conn
from leash_shared.events import AuditEvent, EventType, sanitize_event_data
from principals import Principal, ensure_user, leash_user_id, require_human

router = APIRouter(prefix="/activity", tags=["activity"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])

# Account lifecycle (additive profile types; not yet in shared EventType).
ACCOUNT_CREATED = "account.created"
ACCOUNT_LOGIN = "account.login"
ACCOUNT_LOGOUT = "account.logout"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
STREAM_POLL_SECONDS = 1.5
STREAM_KEEPALIVE_SECONDS = 15.0


class ActivityEventOut(BaseModel):
  sequence: int
  event_id: str
  type: str
  at: str
  user_id: str
  data: dict[str, Any] = Field(default_factory=dict)


class ActivityHistoryOut(BaseModel):
  events: list[ActivityEventOut]
  next_cursor: int | None = None


def _iso(now: datetime) -> str:
  if now.tzinfo is None:
    now = now.replace(tzinfo=timezone.utc)
  return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def emit_activity(
  conn,
  *,
  user_id: str,
  event_type: str,
  data: dict[str, Any] | None = None,
  at: datetime | None = None,
  auth_user_id: str | None = None,
) -> dict[str, Any]:
  """Append one sanitized activity/audit row. Caller commits the transaction."""
  ensure_user(conn, user_id, auth_user_id)
  now = at or datetime.now(timezone.utc)
  payload = dict(data or {})

  try:
    known = EventType(event_type)
    event = AuditEvent(type=known, at=now, user_id=user_id, data=payload)
    record = event.model_dump(mode="json")
    event_id = event.event_id
  except ValueError:
    event_id = "evt_" + uuid4().hex
    record = {
      "event_id": event_id,
      "type": event_type,
      "at": _iso(now),
      "user_id": user_id,
      "data": sanitize_event_data(payload),
    }

  conn.execute(
    "INSERT INTO audit_events (event_id, user_id, record) VALUES (%s, %s, %s)",
    (event_id, user_id, Jsonb(record)),
  )
  conn.execute(
    "INSERT INTO audit_deliveries (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
    (event_id,),
  )
  return record


def emit_for_auth_user(
  conn,
  *,
  auth_user_id: str,
  event_type: str,
  data: dict[str, Any] | None = None,
) -> dict[str, Any]:
  uid = leash_user_id(auth_user_id)
  return emit_activity(
    conn,
    user_id=uid,
    event_type=event_type,
    data=data,
    auth_user_id=auth_user_id,
  )


def _row_to_out(row: dict) -> ActivityEventOut:
  record = row["record"]
  if isinstance(record, str):
    record = json.loads(record)
  at = record.get("at")
  if isinstance(at, datetime):
    at = _iso(at)
  elif not isinstance(at, str):
    at = _iso(datetime.now(timezone.utc))
  return ActivityEventOut(
    sequence=int(row["sequence"]),
    event_id=str(record.get("event_id") or row["event_id"]),
    type=str(record.get("type") or "unknown"),
    at=at,
    user_id=str(record.get("user_id") or row["user_id"]),
    data=dict(record.get("data") or {}),
  )


def list_activity(
  user_id: str,
  *,
  after_sequence: int = 0,
  limit: int = DEFAULT_LIMIT,
) -> list[ActivityEventOut]:
  limit = max(1, min(limit, MAX_LIMIT))
  with get_conn() as conn:
    rows = conn.execute(
      """
      SELECT sequence, event_id, user_id, record
      FROM audit_events
      WHERE user_id = %s AND sequence > %s
      ORDER BY sequence ASC
      LIMIT %s
      """,
      (user_id, after_sequence, limit),
    ).fetchall()
  return [_row_to_out(row) for row in rows]


@router.get("", response_model=ActivityHistoryOut)
def get_activity(
  principal: Annotated[Principal, Depends(require_human)],
  after: Annotated[int, Query(ge=0)] = 0,
  limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ActivityHistoryOut:
  """Historic activity for the authenticated human (resume with `after` sequence)."""
  events = list_activity(principal.user_id, after_sequence=after, limit=limit)
  next_cursor = events[-1].sequence if events else None
  return ActivityHistoryOut(events=events, next_cursor=next_cursor)


@router.get("/stream")
async def stream_activity(
  principal: Annotated[Principal, Depends(require_human)],
  after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
  """SSE: replay from `after`, then poll Postgres for new rows (Bearer auth via fetch)."""
  user_id = principal.user_id

  async def generate():
    cursor = after
    last_ping = asyncio.get_event_loop().time()
    yield f"event: ready\ndata: {json.dumps({'user_id': user_id, 'after': cursor})}\n\n"
    while True:
      batch = await asyncio.to_thread(
        list_activity, user_id, after_sequence=cursor, limit=MAX_LIMIT
      )
      for item in batch:
        cursor = item.sequence
        payload = item.model_dump(mode="json")
        yield f"id: {cursor}\nevent: activity\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
      now = asyncio.get_event_loop().time()
      if now - last_ping >= STREAM_KEEPALIVE_SECONDS:
        yield ": keepalive\n\n"
        last_ping = now
      await asyncio.sleep(STREAM_POLL_SECONDS)

  return StreamingResponse(
    generate(),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )


class InternalActivityIn(BaseModel):
  type: str = Field(min_length=1, max_length=128)
  data: dict[str, Any] = Field(default_factory=dict)
  user_id: str | None = Field(default=None, description="LEASH usr_… when known")
  auth_user_id: str | None = Field(default=None, description="Auth users.id UUID")
  instrument_token: str | None = Field(
    default=None,
    description="Lithic card token used to resolve the owning user when ids omitted",
  )


def _require_internal_bearer(authorization: str | None) -> None:
  expected = os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()
  if not expected:
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="WEBHOOK_INTERNAL_TOKEN is not configured",
    )
  if not authorization or not authorization.lower().startswith("bearer "):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
  token = authorization.split(" ", 1)[1].strip()
  if token != expected:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credential")


def _resolve_leash_user(
  conn,
  *,
  user_id: str | None,
  auth_user_id: str | None,
  instrument_token: str | None,
) -> tuple[str, str | None]:
  if user_id and user_id.startswith("usr_"):
    if auth_user_id:
      return user_id, auth_user_id
    row = conn.execute(
      "SELECT auth_user_id FROM leash_users WHERE id = %s",
      (user_id,),
    ).fetchone()
    auth = str(row["auth_user_id"]) if row and row.get("auth_user_id") else None
    return user_id, auth
  if auth_user_id:
    return leash_user_id(auth_user_id), auth_user_id
  if instrument_token:
    row = conn.execute(
      "SELECT user_id FROM lithic_cards WHERE card_token = %s",
      (instrument_token,),
    ).fetchone()
    if row is None:
      # Signup forever card lives on users.lithic_card_token
      row = conn.execute(
        "SELECT id AS user_id FROM users WHERE lithic_card_token = %s",
        (instrument_token,),
      ).fetchone()
    if row is not None:
      auth_id = str(row["user_id"])
      return leash_user_id(auth_id), auth_id
  raise HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="user_id, auth_user_id, or known instrument_token is required",
  )


@internal_router.post("/activity", status_code=status.HTTP_201_CREATED)
def ingest_activity(
  body: InternalActivityIn,
  authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
  """Service ingest for rail/ASA decisions. Durable write owned by the API."""
  _require_internal_bearer(authorization)
  with get_conn() as conn:
    leash_uid, auth_uid = _resolve_leash_user(
      conn,
      user_id=body.user_id,
      auth_user_id=body.auth_user_id,
      instrument_token=body.instrument_token,
    )
    record = emit_activity(
      conn,
      user_id=leash_uid,
      event_type=body.type,
      data=body.data,
      auth_user_id=auth_uid,
    )
    conn.commit()
  return {"status": "ok", "event_id": str(record["event_id"])}
