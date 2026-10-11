"""Private durable preflight identities. No grants, instruments or charges here.

All mutation callers take the user row lock first. Reconciling is deliberately
terminal in this foundation: a later provider protocol must prove an outcome
before it can add a transition. A retry cannot clear uncertainty.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb

from activity import emit_activity
from authority_errors import AuthorityError
from leash_shared.models import canonical_json
import hashlib


def event(conn, operation, kind, **data):
  row = conn.execute("SELECT auth_user_id FROM leash_users WHERE id=%s", (operation["user_id"],)).fetchone()
  emit_activity(
    conn, user_id=operation["user_id"], event_type="payment.operation." + kind,
    auth_user_id=str(row["auth_user_id"]) if row and row["auth_user_id"] else None,
    data={"payment_id": operation["id"], "run_id": operation["run_id"],
          "mandate_id": operation["mandate_id"], "state": operation["state"], **data},
  )


def prepare(conn, body, principal, mandate):
  digest = hashlib.sha256(canonical_json(body).encode()).hexdigest()
  existing = conn.execute(
    """SELECT * FROM payment_operations WHERE user_id=%s AND agent_id=%s
       AND run_id=%s AND mandate_id=%s AND mandate_version=%s AND checkout_id=%s FOR UPDATE""",
    (principal.user_id, principal.agent_id, body.run_id, mandate.id, mandate.version, body.checkout_id),
  ).fetchone()
  if existing:
    if existing["request_hash"] != digest:
      raise AuthorityError(409, "Payment retry conflicts with the original request")
    return existing
  unresolved = conn.execute(
    """SELECT id FROM payment_operations WHERE user_id=%s
       AND (mandate_id=%s OR run_id=%s) AND state IN ('prepared','reconciling','activating','ready','authorizing','authorized') LIMIT 1""",
    (principal.user_id, mandate.id, body.run_id),
  ).fetchone()
  if unresolved:
    raise AuthorityError(409, "An unresolved payment operation prevents a replacement purchase")
  # Historic approvals may have activated authority in the older implementation.
  if conn.execute(
    """SELECT id FROM payment_attempts WHERE user_id=%s AND mandate_id=%s
       AND status IN ('approved','used') LIMIT 1""", (principal.user_id, mandate.id)
  ).fetchone():
    raise AuthorityError(409, "Historical grant requires reconciliation; no new purchase is authorized")
  operation = conn.execute(
    """INSERT INTO payment_operations
       (id,user_id,agent_id,run_id,mandate_id,mandate_version,mandate_hash,checkout_id,request_hash,
        grant_reference,instrument_reference,issuance_key,authorization_event_id)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
    ("pay_" + uuid4().hex, principal.user_id, principal.agent_id, body.run_id, mandate.id,
     mandate.version, mandate.canonical_payload_hash, body.checkout_id, digest,
     "grt_" + uuid4().hex, uuid4(), uuid4(), uuid4()),
  ).fetchone()
  event(conn, operation, "prepared", financial_authority=False)
  return operation


def finish(conn, operation, state, reason, *, error=None):
  updated = conn.execute(
    """UPDATE payment_operations SET state=%s,revision=revision+1,reason=%s,
       error_status=%s,error_detail=%s,updated_at=now()
       WHERE id=%s AND state='prepared' AND revision=%s RETURNING *""",
    (state, reason, error.status if error else None, error.detail if error else None,
     operation["id"], operation["revision"]),
  ).fetchone()
  if updated is None:
    raise AuthorityError(409, "Payment operation changed; retrieve its original status")
  event(conn, updated, state, reason=reason)
  return updated


def cancel_prepared(conn, user_id, *, reason, run_id=None, mandate_id=None):
  # Called inside the same transaction as stop/revoke/replace. Unknown outcomes
  # stay reconciling; cancelling them would falsely permit another purchase.
  operations = conn.execute(
    """SELECT * FROM payment_operations WHERE user_id=%s AND state='prepared'
       AND (%s::text IS NULL OR run_id=%s) AND (%s::text IS NULL OR mandate_id=%s)
       ORDER BY id FOR UPDATE""", (user_id, run_id, run_id, mandate_id, mandate_id)
  ).fetchall()
  for operation in operations:
    finish(conn, operation, "cancelled", reason)
  # Tombstones are monotonic at the rail. Even if this SQL transaction later
  # rolls back, an old execution cannot regain its spending permission.
  from execution import rail
  executions = conn.execute("""SELECT e.run_id FROM run_executions e
    JOIN agent_runs r ON r.id=e.run_id WHERE r.user_id=%s
    AND (%s::text IS NULL OR r.id=%s) AND (%s::text IS NULL OR r.mandate_id=%s)
    AND e.rail_stopped_at IS NULL ORDER BY e.run_id FOR UPDATE OF e""",
    (user_id, run_id, run_id, mandate_id, mandate_id)).fetchall()
  for execution in executions:
    try:
      result = rail("POST", "/internal/execution/stop", {"run_id": execution["run_id"], "user_id": user_id})
      if (result.get("run_id") == execution["run_id"] and result.get("user_id") == user_id
          and result.get("financial_revocation") == "enforced"):
        conn.execute("UPDATE run_executions SET rail_stopped_at=now() WHERE run_id=%s", (execution["run_id"],))
    except AuthorityError:
      pass  # Pending is explicit; SQL revocation and lease expiry still fail closed.
  return len(operations)


def mark_reconciling(conn, payment_id, user_id, *, expected_revision):
  """Internal fail-closed quarantine; no HTTP route and no provider write/retry."""
  conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (user_id,))
  operation = conn.execute(
    "SELECT * FROM payment_operations WHERE id=%s AND user_id=%s FOR UPDATE", (payment_id, user_id)
  ).fetchone()
  if not operation or operation["revision"] != expected_revision:
    raise AuthorityError(409, "Payment operation revision changed")
  return finish(conn, operation, "reconciling", "outcome_unknown")


def persist_observation(conn, operation, checkout, source_facts):
  assessment = {
    "status": "observed_unverified", "transport": "configured_authenticated_merchant",
    "merchant_ownership": "unverified", "merchant_revision": "unverified",
    "merchant_expiry": "unverified", "checkout_freeze": "unverified",
    "normalization": "user_id/session_id/revision/expiry are API observation context, not merchant proof",
    "financial_authority": False,
  }
  conn.execute(
    """INSERT INTO checkout_observations
       (payment_id,user_id,run_id,mandate_id,mandate_version,mandate_hash,source_hash,
        checkout_hash,source_facts,snapshot,evidence_assessment,observed_at)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
    (operation["id"], operation["user_id"], operation["run_id"], operation["mandate_id"],
     operation["mandate_version"], operation["mandate_hash"], source_facts["facts_hash"],
     checkout.checkout_hash, Jsonb(source_facts), Jsonb(checkout.model_dump(mode="json")),
     Jsonb(assessment), checkout.source.retrieved_at),
  )
  event(conn, operation, "checkout_observed", source_hash=source_facts["facts_hash"],
        checkout_hash=checkout.checkout_hash, evidence_status="observed_unverified")
