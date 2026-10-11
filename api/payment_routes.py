"""Agent payment preflight; verified checkouts receive a local-rail grant once."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from db import get_conn
from leash_shared.models import PaymentProposal
from payment_service import get_payment, request_payment
from principals import Principal, require_agent

router = APIRouter(tags=["payments"])
Agent = Annotated[Principal, Depends(require_agent)]


def checkout_evidence(conn, payment_id):
  from leash_shared.models import CheckoutSnapshot
  from authority_errors import AuthorityError
  from pydantic import ValidationError
  row = conn.execute("SELECT snapshot,checkout_hash FROM checkout_observations WHERE payment_id=%s",(payment_id,)).fetchone()
  if row is None:
    return None
  try:
    snapshot = CheckoutSnapshot.model_validate(row["snapshot"])
    if snapshot.checkout_hash != row["checkout_hash"] or snapshot.purchase_attempt_id != payment_id:
      raise ValueError()
    return snapshot.model_dump(mode="json")
  except (ValueError,ValidationError):
    raise AuthorityError(503,"Stored checkout evidence failed integrity verification") from None


@router.post("/payments")
def create_payment(body: PaymentProposal, principal: Agent, request: Request) -> dict[str, Any]:
  with get_conn() as conn:
    if request.headers.get("x-leash-execution-token"):
      # Run-scoped Graph execution: launch, lease and scope checks, then the
      # execution activation path. One payment path per run, never both.
      from purchase_execution import request_verified
      return request_verified(conn, body, principal, request.headers).model_dump(mode="json")
    # Compatibility is observation-only. It cannot install a grant or charge;
    # all executable payments must use the scoped path above.
    response, _ = request_payment(conn, body, principal)
    return response.model_dump(mode="json")


@router.get("/payments/{payment_id}")
def read_payment(payment_id: str, principal: Agent, request: Request) -> dict[str, Any]:
  with get_conn() as conn:
    if request.headers.get("x-leash-execution-token"):
      from execution import validate_scope
      from purchase_execution import activation, reconcile, response_for
      from authority_errors import AuthorityError
      run, _ = validate_scope(conn, request.headers, "mcp-leash", "check_status", principal=principal, live=False)
      op = conn.execute("SELECT * FROM payment_operations WHERE id=%s AND run_id=%s FOR UPDATE", (payment_id, run["id"])).fetchone()
      if not op:
        raise AuthorityError(404, "Payment not found in this run")
      if activation(conn, payment_id):
        op = reconcile(conn, op)
        result = response_for(conn, op).model_dump(mode="json")
        result.update(payment_execution="ready" if op["state"] == "ready" else op["state"],
          operation={k: op[k] for k in ("state","revision","run_id","checkout_id","mandate_id","mandate_version","mandate_hash")})
        result["operation"]["financial_authority"] = op["state"] == "ready"
        result["rail"] = "local_payment_rail_simulator"
        result["checkout_evidence"] = checkout_evidence(conn,payment_id)
        return result
    result = get_payment(conn, payment_id, principal)
    result["checkout_evidence"] = checkout_evidence(conn,payment_id)
    return result
