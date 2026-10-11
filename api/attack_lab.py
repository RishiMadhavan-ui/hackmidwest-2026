"""Verified operator control plane. Scenario effects stay closed pending owner handoffs."""

from datetime import datetime, timedelta, timezone
import os
import re
import hmac
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.responses import JSONResponse

from auth import get_current_user
from audit_store import append_event
from authority_errors import AuthorityError
from db import get_conn
from principals import Credentials, Principal, ensure_user, leash_user_id, token_digest

router = APIRouter(prefix="/attack-lab", tags=["restricted-attack-lab"])
MAX_BODY = 65536
LIMITS = {"mutations_per_minute": 5, "active_scenarios": 1,
          "candidate_attempts": 3, "scenario_seconds": 120, "payload_bytes": MAX_BODY}


def utc_now() -> datetime:
  return datetime.now(timezone.utc)


def operator_ids() -> set[str]:
  primary = os.getenv("ATTACK_LAB_OPERATOR_USER_IDS", "").strip()
  legacy = os.getenv("ATTACK_LAB_OPERATOR_IDS", "").strip()
  if primary and legacy and set(primary.split(",")) != set(legacy.split(",")):
    raise AuthorityError(503, "Attack Lab operator configuration conflicts")
  value = primary or legacy
  if not value:
    return set()
  items = value.split(",")
  if len(items) > 1000 or any(not re.fullmatch(r"usr_[0-9a-f]{32}", item.strip()) for item in items):
    raise AuthorityError(503, "Attack Lab operator configuration is invalid")
  return {item.strip() for item in items}


def server_enabled() -> bool:
  value = os.getenv("ATTACK_LAB_ENABLED", "0").strip()
  # Missing or malformed flags are disabled; disable controls still work.
  return value == "1"


def require_attack_lab_operator(principal: Principal) -> Principal:
  if principal.role != "human" or principal.user_id not in operator_ids():
    raise AuthorityError(403, "Attack Lab requires an authorized demo operator")
  return principal


def require_operator(request: Request, credentials: Credentials) -> Principal:
  # Verify the current real JWT account/session; the static demo USER_TOKEN,
  # service credentials and role claims never satisfy this dependency.
  user = get_current_user(credentials)
  token = credentials.credentials
  service_keys = {"USER_TOKEN", "STORE_API_TOKEN", "STORE_MCP_TOKEN", "AGENTS_SERVICE_TOKEN",
                  "WEBHOOK_INTERNAL_TOKEN", "WEBHOOK_CHARGE_TOKEN", "RAIL_EVENT_TOKEN"}
  if any(value and hmac.compare_digest(token, value) for name, value in os.environ.items()
         if name in service_keys or name.startswith("AGENT_TOKEN_")):
    raise AuthorityError(403, "Service credentials cannot authorize Attack Lab")
  user_id = leash_user_id(user.id)
  require_attack_lab_operator(Principal("human", user_id))
  if request.method not in {"GET", "HEAD", "OPTIONS"}:
    origin = request.headers.get("origin")
    allowed = {item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")}
    if origin is not None and (origin == "null" or origin not in allowed or origin == "*"):
      raise AuthorityError(403, "Attack Lab request origin is not allowed")
  with get_conn() as conn:
    if conn.execute("SELECT id FROM leash_agents WHERE token_sha256=%s", (token_digest(token),)).fetchone():
      raise AuthorityError(403, "Agent credentials cannot authorize Attack Lab")
    ensure_user(conn, user_id, user.id)
  return Principal("human", user_id)


Operator = Annotated[Principal, Depends(require_operator)]


class EmptyRequest(BaseModel):
  model_config = ConfigDict(extra="forbid")


class ControlRequest(EmptyRequest):
  enabled: StrictBool
  expected_revision: Annotated[StrictInt, Field(ge=1)]


class ScenarioRequest(EmptyRequest):
  scenario: Literal["legitimate_charger", "signature_attack"]


class LabBodyLimit:
  """Bound streamed bodies as well as declared lengths before route parsing."""
  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope["type"] != "http" or not scope["path"].startswith("/attack-lab"):
      return await self.app(scope, receive, send)
    chunks = []
    size = 0
    while True:
      message = await receive()
      if message["type"] == "http.disconnect":
        return
      size += len(message.get("body", b""))
      if size > MAX_BODY:
        return await JSONResponse({"detail": "Attack Lab request exceeds 64 KiB"}, 413)(scope, receive, send)
      chunks.append(message)
      if not message.get("more_body", False):
        break
    async def replay():
      return chunks.pop(0) if chunks else await receive()
    await self.app(scope, replay, send)


def record(conn, principal: Principal, kind: str, data: dict, *, now: datetime):
  append_event(conn, {"event_id": "evt_" + uuid4().hex, "user_id": principal.user_id,
                     "type": "attack_lab." + kind, "at": now.isoformat(), "data": data})


def budget(conn, principal: Principal, *, now: datetime):
  conn.execute("""INSERT INTO attack_lab_rate_windows (operator_user_id,started_at,used)
                  VALUES (%s,%s,0) ON CONFLICT DO NOTHING""", (principal.user_id, now))
  row = conn.execute("SELECT * FROM attack_lab_rate_windows WHERE operator_user_id=%s FOR UPDATE",
                     (principal.user_id,)).fetchone()
  # A clock moving backwards cannot clear an already-full window.
  expired = now >= row["started_at"] + timedelta(minutes=1)
  used = 0 if expired else row["used"]
  if used >= LIMITS["mutations_per_minute"]:
    raise AuthorityError(429, "Attack Lab mutation rate limit exceeded")
  conn.execute("UPDATE attack_lab_rate_windows SET started_at=%s, used=%s WHERE operator_user_id=%s",
               (now if expired else row["started_at"], used + 1, principal.user_id))


def owned(conn, namespace_id: str, principal: Principal, *, lock=False):
  row = conn.execute("SELECT * FROM attack_lab_namespaces WHERE id=%s AND operator_user_id=%s"
                     + (" FOR UPDATE" if lock else ""), (namespace_id, principal.user_id)).fetchone()
  if row is None:
    raise AuthorityError(404, "Attack Lab namespace not found")
  return row


def projection(row):
  return {"id": row["id"], "demo_user_id": row["demo_user_id"], "enabled": row["enabled"],
          "revision": row["revision"], "rail": row["rail"]} if row else None


def access_state(conn, principal):
  row = conn.execute("SELECT * FROM attack_lab_namespaces WHERE operator_user_id=%s",
                     (principal.user_id,)).fetchone()
  from lab_execution import configured
  available = bool(server_enabled() and row and row["enabled"] and configured())
  return {"operator_authorized": True, "server_enabled": server_enabled(),
          "namespace": projection(row), "execution_available": available,
          "reason": "isolated_local_rail_graph" if available else "enable_isolated_workspace_and_configure_execution", "limits": LIMITS}


@router.get("/access")
def access(principal: Operator, response: Response):
  response.headers["Cache-Control"] = "no-store"
  with get_conn() as conn:
    return access_state(conn, principal)


@router.post("/namespaces")
def create_namespace(body: EmptyRequest, principal: Operator):
  if not server_enabled():
    raise AuthorityError(403, "Attack Lab is disabled by server configuration")
  with get_conn() as conn:
    budget(conn, principal, now=utc_now())  # Serialized across API replicas.
    existing = conn.execute("SELECT * FROM attack_lab_namespaces WHERE operator_user_id=%s",
                            (principal.user_id,)).fetchone()
    if existing:
      return access_state(conn, principal)
    namespace_id = "lab_" + uuid4().hex
    demo_user_id = "usr_lab_" + uuid4().hex
    ensure_user(conn, demo_user_id)  # Separate empty identity, no mandate/card/grant.
    conn.execute("""INSERT INTO attack_lab_namespaces (id,operator_user_id,demo_user_id)
                    VALUES (%s,%s,%s)""", (namespace_id, principal.user_id, demo_user_id))
    record(conn, principal, "namespace.created", {"namespace_id": namespace_id, "rail": "local_payment_rail_simulator"}, now=utc_now())
    return access_state(conn, principal)


@router.post("/namespaces/{namespace_id}/control")
def control(namespace_id: str, body: ControlRequest, principal: Operator):
  with get_conn() as conn:
    owned(conn, namespace_id, principal)
    budget(conn, principal, now=utc_now())
    row = owned(conn, namespace_id, principal, lock=True)
    if row["revision"] != body.expected_revision:
      raise AuthorityError(409, "Attack Lab control revision changed")
    if body.enabled and not server_enabled():
      raise AuthorityError(403, "Attack Lab is disabled by server configuration")
    if row["enabled"] != body.enabled:
      conn.execute("""UPDATE attack_lab_namespaces SET enabled=%s,revision=revision+1,updated_at=%s
                      WHERE id=%s""", (body.enabled, utc_now(), namespace_id))
      record(conn, principal, "control.changed", {"namespace_id": namespace_id, "enabled": body.enabled,
        "execution_available": access_state(conn, principal)["execution_available"],
        "cancellation": "not_requested" if body.enabled else "requested"}, now=utc_now())
    result = access_state(conn, principal)
    runs = conn.execute("SELECT run_id FROM attack_lab_runs WHERE namespace_id=%s", (namespace_id,)).fetchall() if not body.enabled else []
    demo = Principal("human", row["demo_user_id"])
  if runs:
    from workflow_control import stop_run
    result["stops"] = [stop_run(item["run_id"], demo) for item in runs]
  return result


def unavailable(namespace_id, principal):
  with get_conn() as conn:
    row = owned(conn, namespace_id, principal)
    if not server_enabled() or not row["enabled"]:
      raise AuthorityError(403, "Attack Lab execution is disabled")
    # No flag, role or operator confirmation can bypass missing downstream
    # isolation, worker/Stop fencing or payment-authority implementation.
    raise AuthorityError(503, "Attack Lab execution awaits isolated fixture/rail and Graph integration")


def scenario(namespace_id: str, body: ScenarioRequest, principal: Operator):
  unavailable(namespace_id, principal)


@router.post("/namespaces/{namespace_id}/replays")
@router.post("/namespaces/{namespace_id}/tamper")
@router.post("/namespaces/{namespace_id}/simulate-authorization")
def blocked_operation(namespace_id: str, body: EmptyRequest, principal: Operator):
  unavailable(namespace_id, principal)


def attack_lab_status(principal: Principal):
  require_attack_lab_operator(principal)
  with get_conn() as conn:
    state = access_state(conn, principal)
  return {**state, "execution": state["reason"], "can_run_attacks": state["execution_available"]}


@router.get("/status")
def status(principal: Operator):
  return attack_lab_status(principal)


@router.post("/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str, principal: Operator):
  raise AuthorityError(503 if server_enabled() else 403,
                       "Use an enabled isolated namespace; direct scenario execution is disabled")


@router.get("/products/{product_id}")
def product_preview(product_id: str, principal: Operator):
  # No raw HTML from a merchant is served in the application's origin.
  raise AuthorityError(503 if server_enabled() else 403, "Isolated listing preview is not configured")
