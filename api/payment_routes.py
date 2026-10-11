"""Agent payment preflight; unfinished financial authority always fails closed."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from db import get_conn
from leash_shared.models import PaymentProposal
from payment_service import get_payment, request_payment
from principals import Principal, require_agent

router = APIRouter(tags=["payments"])
Agent = Annotated[Principal, Depends(require_agent)]


@router.post("/payments")
def create_payment(body: PaymentProposal, principal: Agent) -> dict[str, Any]:
  with get_conn() as conn:
    response = request_payment(conn, body, principal)
  return response.model_dump(mode="json")


@router.get("/payments/{payment_id}")
def read_payment(payment_id: str, principal: Agent) -> dict[str, Any]:
  with get_conn() as conn:
    return get_payment(conn, payment_id, principal)
