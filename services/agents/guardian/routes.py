from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from guardian import evaluate

router = APIRouter()


# TODO: switch to leash_shared.models (Mandate, Cart, ProvenanceEvent) once
# models.py lands. Dicts for now so this doesn't drift from Rishi's shapes.
class EvaluateRequest(BaseModel):
  mandate: dict[str, Any]
  cart: dict[str, Any]
  provenance: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/guardian/evaluate")
def guardian_evaluate(req: EvaluateRequest) -> dict[str, Any]:
  return evaluate(req.mandate, req.cart, req.provenance)
