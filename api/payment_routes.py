"""Agent payment proposals: independent verify + grant, never agent cart proof."""

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
    conn.commit()
  out = response.model_dump(mode="json")
  instrument = getattr(response, "_instrument_token", None)
  last4 = getattr(response, "_card_last4", None)
  if instrument and out.get("status") == "approved":
    # Once for the approved caller so complete_checkout can present the bound instrument.
    out["instrument_token"] = instrument
    if last4:
      out["card_last4"] = last4
  return out


@router.get("/payments/{payment_id}")
def read_payment(payment_id: str, principal: Agent) -> dict[str, Any]:
  with get_conn() as conn:
    return get_payment(conn, payment_id, principal)
