"""User-scoped activity history and SSE stream over durable audit_events.

Writes go through the same append-only audit_events table as mandate authority
events so Mission Control / R06 can later fan out from one source. Account
lifecycle types (account.*) are stored as sanitized envelopes; shared EventType
members (card.issued, payment.*, guardian.*, etc.) validate via AuditEvent.
"""

from __future__ import annotations

import asyncio
import json
import os
import hmac
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from audit_store import append_event
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.events import AuditEvent, EventType, sanitize_event_data
from leash_shared.models import Contract, Text, UserId, Cents, Mcc, UtcDatetime
from principals import Credentials, Principal, ensure_user, human_from_credentials, leash_user_id, require_human

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
  # Events preserve an existing identity binding. Internal domain callers know
  # the LEASH identity, but need not repeat its authentication-provider UUID.
  # Creating a new binding still goes through ensure_user's ownership check.
  if auth_user_id is None:
    existing = conn.execute("SELECT auth_user_id FROM leash_users WHERE id=%s", (user_id,)).fetchone()
    if existing:
      auth_user_id = existing["auth_user_id"]
  ensure_user(conn, user_id, auth_user_id)
  now = at or datetime.now(timezone.utc)
  payload = dict(data or {})

  if event_type in EventType._value2member_map_:
    event = AuditEvent(type=EventType(event_type), at=now, user_id=user_id, data=payload)
    record = event.model_dump(mode="json")
  else:
    event_id = "evt_" + uuid4().hex
    record = {
      "event_id": event_id,
      "type": event_type,
      "at": _iso(now),
      "user_id": user_id,
      "data": sanitize_event_data(payload),
    }

  append_event(conn, record)
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
    raise ValueError("Stored activity timestamp is missing")
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
  after: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
  limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ActivityHistoryOut:
  """Historic activity for the authenticated human (resume with `after` sequence)."""
  events = list_activity(principal.user_id, after_sequence=after, limit=limit)
  next_cursor = events[-1].sequence if events else None
  return ActivityHistoryOut(events=events, next_cursor=next_cursor)


@router.get("/stream")
async def stream_activity(
  request: Request,
  principal: Annotated[Principal, Depends(require_human)],
  credentials: Credentials,
  after: Annotated[int | None, Query(ge=0, le=9223372036854775807)] = None,
  last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
  """SSE: replay from `after`, then poll Postgres for new rows (Bearer auth via fetch)."""
  user_id = principal.user_id
  try:
    cursor_start = after if after is not None else int(last_event_id or "0")
    if not 0 <= cursor_start <= 9223372036854775807:
      raise ValueError()
  except ValueError:
    raise AuthorityError(422, "Invalid replay cursor") from None

  async def generate():
    cursor = cursor_start
    last_auth = 0.0
    last_ping = asyncio.get_event_loop().time()
    yield f"event: ready\ndata: {json.dumps({'user_id': user_id, 'after': cursor})}\n\n"
    while not await request.is_disconnected():
      tick = asyncio.get_running_loop().time()
      if tick - last_auth >= STREAM_KEEPALIVE_SECONDS:
        try:
          await asyncio.to_thread(human_from_credentials, credentials)
        except Exception:
          yield 'event: unavailable\ndata: {"detail":"Session or database unavailable"}\n\n'
          return
        last_auth = tick
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


class RailDecisionData(Contract):
  event_id: Text = Field(max_length=128)
  result: Literal["APPROVED", "DECLINED"]
  reason: Text = Field(max_length=128)
  rail: Literal["local_payment_rail_simulator", "lithic_sandbox"]
  decision_source: Literal["local_rail", "lithic_asa"]
  provider: Literal["local_rail", "lithic_sandbox"]
  amount_cents: Cents
  currency: Literal["USD"]
  descriptor: Text = Field(max_length=200)
  mcc: Mcc
  decided_at: UtcDatetime


class InternalActivityIn(Contract):
  event_id: Text = Field(max_length=128)
  type: Literal["authorization.decided"]
  data: RailDecisionData
  user_id: UserId | None = None
  auth_user_id: str | None = Field(default=None, max_length=128)
  instrument_token: Text | None = Field(default=None, max_length=128)


def _require_internal_bearer(authorization: str | None) -> None:
  expected = os.getenv("RAIL_EVENT_TOKEN", "").strip()
  if len(expected) < 32 or expected == os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip():
    raise HTTPException(503, "Distinct rail event credential is not configured")
  if not authorization or not hmac.compare_digest(authorization, "Bearer " + expected):
    raise HTTPException(401, "Invalid rail event credential")


def _resolve_leash_user(conn, *, user_id, auth_user_id, instrument_token):
  candidates = []
  if user_id:
    candidates.append(user_id)
  if auth_user_id:
    try:
      from uuid import UUID
      candidates.append(leash_user_id(str(UUID(auth_user_id))))
    except ValueError:
      raise HTTPException(422, "Invalid auth user id") from None
  if instrument_token:
    rows = conn.execute(
      """SELECT user_id FROM lithic_cards WHERE card_token=%s
         UNION SELECT id AS user_id FROM users WHERE lithic_card_token=%s""",
      (instrument_token, instrument_token),
    ).fetchall()
    candidates.extend(leash_user_id(str(row["user_id"])) for row in rows)
  if not candidates or any(uid != candidates[0] for uid in candidates):
    raise HTTPException(422, "Rail event owner is missing or inconsistent")
  # Never invent accounts or change identity mappings during service ingestion.
  row = conn.execute("SELECT id FROM leash_users WHERE id=%s", (candidates[0],)).fetchone()
  if row is None:
    raise HTTPException(422, "Rail event owner does not exist")
  return candidates[0]


def _financial_payload(data):
  value = sanitize_event_data(data)
  if value.get("result") not in {"APPROVED", "DECLINED"} or value.get("rail") not in {
    "local_payment_rail_simulator", "lithic_sandbox"
  } or not isinstance(value.get("event_id"), str):
    raise HTTPException(422, "Invalid authorization decision event")
  # Retry delivery latency is observational; it cannot turn the original
  # decision into a conflicting financial outcome or another history entry.
  return {key: item for key, item in value.items() if key != "latency_ms"}


@internal_router.post("/activity", status_code=201)
def ingest_activity(body: InternalActivityIn, authorization: Annotated[str | None, Header()] = None):
  """Dedicated rail publisher; append an original decision once, never authority."""
  _require_internal_bearer(authorization)
  payload = body.data.model_dump(mode="json")
  _financial_payload(payload)
  if (payload["rail"], payload["decision_source"], payload["provider"]) not in {
    ("local_payment_rail_simulator", "local_rail", "local_rail"),
    ("lithic_sandbox", "lithic_asa", "lithic_sandbox"),
  }:
    raise HTTPException(422, "Inconsistent authorization rail attribution")
  with get_conn() as conn:
    user_id = _resolve_leash_user(conn, user_id=body.user_id,
      auth_user_id=body.auth_user_id, instrument_token=body.instrument_token)
    conn.execute("SELECT pg_advisory_xact_lock(781202606)")
    previous = conn.execute("SELECT record FROM audit_events WHERE event_id=%s", (body.event_id,)).fetchone()
    if previous:
      record = previous["record"]
      if record["user_id"] != user_id or record["type"] != body.type or _financial_payload(record["data"]) != _financial_payload(payload):
        raise HTTPException(422, "Event id conflicts with original decision")
      raise HTTPException(409, "Event is already stored")
    record = AuditEvent(event_id=body.event_id, type=EventType.AUTHORIZATION_DECIDED,
      user_id=user_id, data=payload).model_dump(mode="json")
    append_event(conn, record)
  return {"status": "stored", "event_id": body.event_id}
