"""Durable immutable checkout facts written only by the configured merchant."""

import hmac
import os
import re
from datetime import timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from psycopg.types.json import Jsonb

from authority_errors import AuthorityError
from db import get_conn
from execution import enabled, validate_scope
from leash_shared.models import Contract, canonical_json
from mandate_service import utc_now
from payment_service import _map_checkout

router = APIRouter(prefix="/internal/merchant", tags=["merchant execution"])


def merchant_auth(authorization: Annotated[str | None, Header()] = None):
  token = os.getenv("MERCHANT_BACKEND_TOKEN", "")
  if len(token) < 32 or token in {os.getenv("STORE_API_TOKEN"), os.getenv("STORE_MCP_TOKEN")}:
    raise AuthorityError(503, "Distinct merchant backend credential is not configured")
  if not authorization or not hmac.compare_digest(authorization, "Bearer " + token):
    raise AuthorityError(403, "Merchant backend credential required")


class Facts(Contract):
  facts: dict[str, Any]


@router.post("/checkouts", dependencies=[Depends(merchant_auth)], status_code=201)
def persist_checkout(body: Facts, request: Request):
  enabled()
  from leash_shared.events import sanitize_event_data
  facts = body.facts
  if len(canonical_json(facts)) > 32000 or sanitize_event_data(facts) != facts:
    raise AuthorityError(422, "Invalid merchant evidence")
  with get_conn() as conn:
    run, lease = validate_scope(conn, request.headers, "mcp-store", "create_checkout")
    cid = facts.get("checkout_id", "")
    if not isinstance(cid, str) or not re.fullmatch(r"ckt_[a-f0-9]{16,64}", cid):
      raise AuthorityError(422, "Invalid merchant checkout identity")
    _map_checkout(facts, user_id=run["user_id"], payment_id="pay_validation", now=utc_now())
    old = conn.execute("SELECT * FROM merchant_checkouts WHERE checkout_id=%s", (cid,)).fetchone()
    if old:
      if old["run_id"] != run["id"] or old["facts"] != facts:
        raise AuthorityError(409, "Checkout identity conflicts")
      return checkout_projection(old)
    count = conn.execute("SELECT count(*) n FROM merchant_checkouts WHERE run_id=%s", (run["id"],)).fetchone()["n"]
    if count >= 3:
      raise AuthorityError(409, "Candidate limit reached")
    row = conn.execute("""INSERT INTO merchant_checkouts
      (checkout_id,user_id,run_id,generation,session_id,expires_at,facts,facts_hash)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
      (cid, run["user_id"], run["id"], lease["generation"], "ses_" + uuid4().hex,
       min(lease["deadline"], utc_now()+timedelta(minutes=15)), Jsonb(facts), facts["facts_hash"])).fetchone()
    return checkout_projection(row)


def checkout_projection(row):
  return {**row["facts"], "user_id": row["user_id"], "run_id": row["run_id"],
    "generation": row["generation"], "session_id": row["session_id"], "revision": row["revision"],
    "expires_at": row["expires_at"].isoformat(), "frozen": True, "provider": "simulated_merchant"}


@router.get("/checkouts/{checkout_id}", dependencies=[Depends(merchant_auth)])
def get_checkout(checkout_id: str):
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM merchant_checkouts WHERE checkout_id=%s", (checkout_id,)).fetchone()
    if not row:
      raise AuthorityError(404, "Checkout not found")
    return checkout_projection(row)
