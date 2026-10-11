"""Human-triggered shopping start. Proxies to agents with the service token.

Creates a fresh human launch first (run_id + launch_id), then queues agents.
The browser never receives AGENTS_SERVICE_TOKEN, agent credentials, or launch_id.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from activity import emit_activity
from authority_errors import AuthorityError
from db import get_conn
from execution import Launch, launch as create_human_launch
from leash_shared.models import MandateStatus, PurchaseMandate
from mandate_service import current_mandate, utc_now
from principals import Principal, require_human, token_digest
from workflow_control import lock_user_authority

router = APIRouter(tags=["shopping"])

DEMO_TASK = "Buy a USB-C laptop charger for under $40. No subscriptions."


class StartShoppingBody(BaseModel):
  mandate_id: str = Field(min_length=8, max_length=128)
  # live = real Strands shopper; scripted = labeled fixture tool path.
  agent_mode: Literal["live", "scripted"] = "live"
  # scripted targets only; ignored for live.
  scenario: Literal["charger", "subscription_attack"] = "charger"


def _agents_url() -> str:
  return os.getenv("AGENTS_URL", "").strip().rstrip("/")


def _agents_service_token() -> str:
  return os.getenv("AGENTS_SERVICE_TOKEN", "").strip()


def _store_start_url(product_id: str) -> str | None:
  base = os.getenv("STORE_URL", "").strip().rstrip("/")
  if not base:
    return None
  return f"{base}/products/{product_id}"


def _auth_id(conn, user_id: str) -> str | None:
  row = conn.execute(
    "SELECT auth_user_id FROM leash_users WHERE id=%s", (user_id,)
  ).fetchone()
  return str(row["auth_user_id"]) if row and row["auth_user_id"] else None


def _scenario_fields(body: StartShoppingBody) -> dict[str, Any]:
  extra: dict[str, Any] = {}
  if body.agent_mode == "scripted":
    if body.scenario == "subscription_attack":
      extra["sku"] = "SUB-CARE-MO"
      extra["claim_sku"] = "CHG-65W"
      start = _store_start_url("voltcare")
    else:
      extra["sku"] = "CHG-65W"
      start = _store_start_url("chg-65w")
  else:
    start = _store_start_url("chg-65w")
  if start:
    extra["start_url"] = start
  return extra


def _agents_payload(
  body: StartShoppingBody,
  *,
  task: str,
  run_id: str,
  launch_id: str,
  agent_mode: str,
) -> dict[str, Any]:
  payload: dict[str, Any] = {
    "task": task,
    "mandate_id": body.mandate_id,
    "agent_mode": agent_mode,
    "run_id": run_id,
    "launch_id": launch_id,
  }
  payload.update(_scenario_fields(body))
  return payload


def _cluster_shopper_env(agent_mode: str) -> str:
  return (
    "AGENT_TOKEN_SHOPPER"
    if agent_mode == "live"
    else "AGENT_TOKEN_SHOPPER_SCRIPTED"
  )


def require_claimable_shopper(
  conn, mandate: PurchaseMandate, *, agent_mode: str
) -> None:
  """Refuse launches the agents pod cannot claim with its mode credential.

  Agents authenticate as the leash_agents row bound to AGENT_TOKEN_SHOPPER
  (live) or AGENT_TOKEN_SHOPPER_SCRIPTED. Mission Control mandates that use a
  random UI-only agent produce claim 404 and a stuck queued run.
  """
  env_name = _cluster_shopper_env(agent_mode)
  token = os.getenv(env_name, "").strip()
  if len(token) < 32:
    raise AuthorityError(
      503,
      f"Shopping start requires {env_name} on the API",
    )
  bound = conn.execute(
    """SELECT id, user_id FROM leash_agents
       WHERE token_sha256 = %s AND enabled""",
    (token_digest(token),),
  ).fetchone()
  if bound is None:
    raise AuthorityError(
      503,
      f"{env_name} is not bound to an enabled shopper agent",
    )
  if (
    str(bound["user_id"]) != mandate.user_id
    or str(bound["id"]) != mandate.agent_id
  ):
    raise AuthorityError(
      409,
      "This mandate's shopper is not bound to the cluster agent credential; "
      "an operator must bind-agent for this account before Start shopping",
    )


@router.post("/shopping/start")
def start_shopping(
  body: StartShoppingBody,
  principal: Annotated[Principal, Depends(require_human)],
) -> dict[str, Any]:
  """Mint a human launch, then queue the agents Graph for that launch only."""
  agents = _agents_url()
  token = _agents_service_token()
  if not agents or len(token) < 32:
    raise AuthorityError(503, "Shopping start is not configured")

  with get_conn() as conn:
    lock_user_authority(conn, principal.user_id)
    mandate = current_mandate(
      conn, body.mandate_id, principal, now=utc_now(), lock=True
    )
    if mandate.status != MandateStatus.ACTIVE:
      raise AuthorityError(409, "Only a confirmed active mandate can start shopping")
    if not mandate.valid_from <= utc_now() < mandate.valid_until:
      raise AuthorityError(409, "Mandate is outside its validity window")
    if mandate.canonical_payload_hash is None:
      raise AuthorityError(409, "Mandate hash is missing")
    agent = conn.execute(
      """SELECT allowed_modes FROM leash_agents
         WHERE id = %s AND user_id = %s AND enabled""",
      (mandate.agent_id, principal.user_id),
    ).fetchone()
    if not agent or len(agent["allowed_modes"]) != 1:
      raise AuthorityError(409, "Mandate agent has not been provisioned")
    shopper_mode = str(agent["allowed_modes"][0])
    if body.agent_mode != shopper_mode:
      raise AuthorityError(
        409,
        f"This mandate's shopper is provisioned for {shopper_mode} mode only",
      )
    require_claimable_shopper(conn, mandate, agent_mode=shopper_mode)
    task = (mandate.description or "").strip() or DEMO_TASK
    start_url = _scenario_fields(body).get("start_url")

  # Durable launch + run registration (hashed launch secret; secret returned once).
  launched = create_human_launch(
    Launch(
      mandate_id=mandate.id,
      version=mandate.version,
      canonical_payload_hash=mandate.canonical_payload_hash,
      confirmed=True,
      start_url=start_url,
    ),
    principal,
  )
  launched_mode = str(launched.get("agent_mode") or "live")
  if body.agent_mode != launched_mode:
    raise AuthorityError(
      409,
      f"This mandate's shopper is provisioned for {launched_mode} mode only",
    )

  run_id = str(launched["run_id"])
  launch_id = str(launched["launch_id"])
  payload = _agents_payload(
    body,
    task=task,
    run_id=run_id,
    launch_id=launch_id,
    agent_mode=launched_mode,
  )

  try:
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
      res = client.post(
        f"{agents}/runs",
        headers={
          "Authorization": f"Bearer {token}",
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        json=payload,
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Agents service unreachable") from exc

  if res.status_code >= 400:
    detail = "Agents service rejected the shopping start"
    try:
      err = res.json()
      if isinstance(err, dict) and err.get("detail"):
        detail = str(err["detail"])[:200]
    except ValueError:
      pass
    raise AuthorityError(502 if res.status_code >= 500 else 409, detail)

  try:
    data = res.json()
  except ValueError as exc:
    raise AuthorityError(502, "Agents service returned an invalid response") from exc

  if data.get("run_id") != run_id:
    raise AuthorityError(502, "Agents service returned a different run_id")

  with get_conn() as conn:
    emit_activity(
      conn,
      user_id=principal.user_id,
      event_type="shopping.start.requested",
      data={
        "run_id": run_id,
        "mandate_id": body.mandate_id,
        "agent_mode": launched_mode,
        "scenario": body.scenario if launched_mode == "scripted" else "live",
        "status": data.get("status") or "accepted",
      },
      auth_user_id=_auth_id(conn, principal.user_id),
    )

  return {
    "run_id": run_id,
    "status": data.get("status") or "accepted",
    "agent_mode": launched_mode,
    "mandate_id": body.mandate_id,
    "scenario": body.scenario if launched_mode == "scripted" else "live",
    "label": (
      "Simulated compromised agent"
      if launched_mode == "scripted" and body.scenario == "subscription_attack"
      else "Simulated scripted shopper"
      if launched_mode == "scripted"
      else "Live Strands shopper"
    ),
  }
