from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from guardian import evaluate

router = APIRouter()


# TODO: switch to leash_shared.models once R01 is frozen. Dicts for now so this
# doesn't drift from Rishi's shapes.
class EvaluateRequest(BaseModel):
  mandate: dict[str, Any]
  # The trusted checkout the api fetched from the merchant. Without it the
  # guardian can only recommend review.
  checkout: dict[str, Any] | None = None
  # The agent's own description of the purchase. A claim, not proof.
  proposal: dict[str, Any] | None = Field(default=None, alias="cart")
  provenance: list[dict[str, Any]] = Field(default_factory=list)
  trace: list[dict[str, Any]] = Field(default_factory=list)

  model_config = {"populate_by_name": True}


@router.post("/guardian/evaluate")
def guardian_evaluate(req: EvaluateRequest) -> dict[str, Any]:
  return evaluate(
    req.mandate,
    checkout=req.checkout,
    proposal=req.proposal,
    provenance=req.provenance,
    trace=req.trace,
  )
