"""Attack Lab operator boundary. Fail closed without an explicit allowlist."""

from __future__ import annotations

import os
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from authority_errors import AuthorityError
from principals import Principal, require_human

router = APIRouter(prefix="/attack-lab", tags=["attack lab"])


def _operator_ids() -> set[str]:
  raw = os.getenv("ATTACK_LAB_OPERATOR_USER_IDS", "").strip()
  if not raw:
    return set()
  return {part.strip() for part in raw.split(",") if part.strip()}


def _attack_lab_token() -> str:
  return os.getenv("ATTACK_LAB_TOKEN", "").strip()


def _store_url() -> str:
  return os.getenv("STORE_URL", "").strip().rstrip("/")


def require_attack_lab_operator(
  principal: Annotated[Principal, Depends(require_human)],
) -> Principal:
  """Server-verified human + allowlist. Service/agent tokens never suffice."""
  allowed = _operator_ids()
  if not allowed or principal.user_id not in allowed:
    raise AuthorityError(403, "Attack Lab execution requires an authorized demo operator")
  return principal


@router.get("/status")
def attack_lab_status(
  principal: Annotated[Principal, Depends(require_human)],
) -> dict[str, Any]:
  allowed = _operator_ids()
  operator = bool(allowed and principal.user_id in allowed)
  configured = bool(allowed) and len(_attack_lab_token()) >= 32 and bool(_store_url())
  return {
    "execution": "operator_gated" if configured else "disabled_pending_configuration",
    "operator_authorized": operator,
    "can_run_attacks": operator and configured,
  }


@router.get("/products/{product_id}")
def attack_lab_product(
  product_id: str,
  _: Annotated[Principal, Depends(require_attack_lab_operator)],
) -> HTMLResponse:
  """Poisoned listing preview for authorized operators only."""
  token = _attack_lab_token()
  store = _store_url()
  if len(token) < 32 or not store:
    raise AuthorityError(503, "Attack Lab merchant credential is not configured")
  try:
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
      res = client.get(
        f"{store}/internal/attack-lab/products/{product_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
        params={"evil": "1"},
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Attack Lab merchant unreachable") from exc
  if res.status_code == 404:
    raise AuthorityError(404, "Unknown Attack Lab product")
  if res.status_code == 403:
    raise AuthorityError(403, "Attack Lab execution denied by merchant")
  if not res.is_success:
    raise AuthorityError(502, "Attack Lab merchant rejected the request")
  return HTMLResponse(
    content=res.text,
    status_code=200,
    headers={"Cache-Control": "no-store", "X-Leash-Attack-Lab": "operator"},
  )


@router.post("/scenarios/{scenario_id}/start")
def start_scenario(
  scenario_id: str,
  _: Annotated[Principal, Depends(require_attack_lab_operator)],
) -> dict[str, Any]:
  """Mutation entrypoint: authorized operators only; scenarios remain bounded."""
  # Fixture isolation / Graph execution remain follow-on work. This route exists
  # so unauthorized callers receive 403 at the API boundary before any effect.
  raise AuthorityError(
    503,
    f"Attack Lab scenario '{scenario_id}' is not enabled until isolated demo fixtures are provisioned",
  )
