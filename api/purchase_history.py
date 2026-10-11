"""Human-owned preflight history/evidence. Observations never become paid receipts."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError

from authority_errors import AuthorityError
from db import get_conn
from leash_shared.models import CheckoutSnapshot, PaymentResponse, canonical_json
from mandate_service import version_record, utc_now
from principals import Principal, require_human

router = APIRouter(prefix="/purchase-attempts", tags=["human-purchase-evidence"])
Human = Annotated[Principal, Depends(require_human)]


@router.post("/{payment_id}/reconcile")
def reconcile_owned(payment_id: str, principal: Human, response: Response):
  """Read the original cached rail event. Never install, charge or retry."""
  from purchase_execution import reconcile
  response.headers["Cache-Control"] = "no-store"
  with get_conn() as conn:
    conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
    owner_operation(conn, payment_id, principal)
    op = conn.execute("SELECT * FROM payment_operations WHERE id=%s AND user_id=%s FOR UPDATE",
                      (payment_id, principal.user_id)).fetchone()
    reconcile(conn, op)
    return summary(owner_operation(conn, payment_id, principal), conn)


def owner_operation(conn, payment_id, principal):
  row = conn.execute("""SELECT o.*,p.record FROM payment_operations o
                        LEFT JOIN payment_attempts p ON p.id=o.id
                        WHERE o.id=%s AND o.user_id=%s""", (payment_id, principal.user_id)).fetchone()
  if row is None:
    raise AuthorityError(404, "Purchase attempt not found")
  return row


def summary(row, conn=None):
  result = None
  if row["record"]:
    try:
      result = PaymentResponse.model_validate(row["record"])
    except ValidationError:
      raise AuthorityError(503, "Purchase result failed integrity validation") from None
    if result.id != row["id"]:
      raise AuthorityError(503, "Purchase result failed integrity validation")
  scoped = conn and conn.execute("SELECT 1 FROM payment_activations WHERE payment_id=%s", (row["id"],)).fetchone()
  authorized = False
  if scoped:
    from purchase_execution import response_for
    result = response_for(conn, row)
    outcome = conn.execute("SELECT record FROM payment_outcomes WHERE payment_id=%s", (row["id"],)).fetchone()
    authorized = bool(row["state"] == "authorized" and outcome and outcome["record"].get("result") == "APPROVED")
    if row["state"] == "authorized" and not authorized:
      raise AuthorityError(503, "Authorization outcome is not verified")
  return {"id": row["id"], "run_id": row["run_id"], "mandate_id": row["mandate_id"],
          "mandate_version": row["mandate_version"], "checkout_id": row["checkout_id"],
          "state": row["state"], "revision": row["revision"], "reason": row["reason"],
          "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
          "result": result.model_dump(mode="json") if result else None,
          "financial_authority": bool(scoped and row["state"] == "ready"),
          "payment_execution": row["state"] if scoped else "unavailable",
          "authorization_status": "authorized" if authorized else "unverified",
          "rail": "local_payment_rail_simulator" if scoped else None,
          "history_kind": "scoped_execution" if scoped else "preflight_only"}


@router.get("")
def history(principal: Human, response: Response, limit: int = Query(default=25, ge=1, le=100),
            before: str | None = Query(default=None, min_length=5, max_length=128)):
  response.headers["Cache-Control"] = "no-store"
  with get_conn() as conn:
    cursor = owner_operation(conn, before, principal) if before else None
    rows = conn.execute("""SELECT o.*,p.record FROM payment_operations o
                           LEFT JOIN payment_attempts p ON p.id=o.id WHERE o.user_id=%s
                           AND (%s::timestamptz IS NULL OR (o.created_at,o.id)<(%s,%s))
                           ORDER BY o.created_at DESC,o.id DESC LIMIT %s""",
                        (principal.user_id, cursor["created_at"] if cursor else None,
                         cursor["created_at"] if cursor else None, before, limit+1)).fetchall()
    return {"attempts": [summary(row, conn) for row in rows[:limit]],
            "next_cursor": rows[limit-1]["id"] if len(rows) > limit else None}


@router.get("/{payment_id}")
def evidence(payment_id: str, principal: Human, response: Response):
  response.headers["Cache-Control"] = "no-store"
  with get_conn() as conn:
    row = owner_operation(conn, payment_id, principal)
    mandate = version_record(conn, row["mandate_id"], row["mandate_version"], now=utc_now())
    if mandate.user_id != principal.user_id or mandate.canonical_payload_hash != row["mandate_hash"]:
      raise AuthorityError(503, "Purchase authority failed integrity validation")
    observation = conn.execute("SELECT * FROM checkout_observations WHERE payment_id=%s AND user_id=%s",
                               (payment_id, principal.user_id)).fetchone()
    observed = None
    if observation:
      try:
        checkout = CheckoutSnapshot.model_validate(observation["snapshot"])
        fields = ("checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents")
        facts = {key: observation["source_facts"][key] for key in fields}
        digest = hashlib.sha256(canonical_json(facts).encode()).hexdigest()
        if (checkout.checkout_hash != observation["checkout_hash"] or digest != observation["source_hash"]
            or checkout.user_id != principal.user_id or checkout.purchase_attempt_id != payment_id):
          raise ValueError("Stored evidence mismatch")
      except (ValidationError, ValueError, KeyError, TypeError):
        raise AuthorityError(503, "Purchase evidence failed integrity validation") from None
      observed = {"checkout": checkout.model_dump(mode="json"), "source_hash": digest,
                  "observed_at": observation["observed_at"].isoformat(),
                  "assessment": observation["evidence_assessment"]}
    return {"attempt": summary(row, conn), "mandate": mandate.model_dump(mode="json"),
            "observation": observed, "evidence_status": observation["evidence_assessment"]["status"] if observed else "not_observed"}
