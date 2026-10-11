"""Register a run with the Leash api before it emits a single trace event.

The api binds the run to the agent's authenticated user, the mandate, its
confirmed version and hash, and the live/scripted label. Only then will it
accept traces for that run_id. If registration fails, the run doesn't start:
an unregistered run would produce evidence the api has to reject.
"""

import os
from typing import Any

import httpx

# TODO: confirm the route and body with Rishi (R02/R06). AgentRun in
# leash_shared.models carries id, mandate_id, agent_mode, model, provider; the
# api fills user_id, agent_id, mandate_version, and mandate_hash itself.
RUN_REGISTRATION_PATH = "/agent-runs"
TIMEOUT_SECONDS = 10.0


class RegistrationError(RuntimeError):
  pass


def register_run(
  run_id: str,
  mandate_id: str | None,
  agent_mode: str,
  token: str,
  model: str | None = None,
  provider: str | None = None,
) -> dict[str, Any]:
  """Register with the credential bound to this run's mode (see credentials.py)."""
  api_url = os.environ["API_URL"].rstrip("/")
  if not mandate_id:
    raise RegistrationError("a run needs a mandate_id before Leash will register it")
  body = {
    "id": run_id,
    "mandate_id": mandate_id,
    "agent_mode": agent_mode,
    "model": model,
    "provider": provider,
  }
  try:
    res = httpx.post(
      api_url + RUN_REGISTRATION_PATH,
      json=body,
      headers={"Authorization": f"Bearer {token}"},
      timeout=TIMEOUT_SECONDS,
    )
  except httpx.HTTPError as exc:
    raise RegistrationError(f"Leash api unreachable ({type(exc).__name__})") from exc
  try:
    payload = res.json()
  except ValueError:
    payload = {}
  if not res.is_success:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    raise RegistrationError(detail or f"Leash api returned HTTP {res.status_code}")
  # The api must echo exactly what it committed. A missing or null mode is not
  # a yes: a scripted run must never end up recorded as live, or the reverse.
  if not isinstance(payload, dict) or payload.get("id") != run_id:
    raise RegistrationError("Leash api registered a different run id")
  if payload.get("agent_mode") != agent_mode:
    raise RegistrationError("Leash api did not confirm this run's agent mode")
  return payload
