"""Human JWT/demo credentials and explicitly provisioned agent ownership."""

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import TypeAdapter

from auth import bearer_scheme, get_current_user
from authority_errors import AuthorityError
from db import get_conn
from leash_shared.models import AgentId, UserId


@dataclass(frozen=True)
class Principal:
  role: Literal["human", "agent"]
  user_id: str
  agent_id: str | None = None
  allowed_modes: tuple[str, ...] = ()
  delegated_run: str | None = None


Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def credential_token(credentials: HTTPAuthorizationCredentials | None) -> str:
  if credentials is None or credentials.scheme.lower() != "bearer":
    raise AuthorityError(401, "Not authenticated")
  return credentials.credentials


def token_digest(token: str) -> str:
  return hashlib.sha256(token.encode("utf-8")).hexdigest()


def leash_user_id(auth_id: str) -> str:
  return "usr_" + uuid.UUID(auth_id).hex


def ensure_user(conn, user_id: str, auth_id: str | None = None) -> None:
  TypeAdapter(UserId).validate_python(user_id)
  conn.execute(
    "INSERT INTO leash_users (id, auth_user_id) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
    (user_id, auth_id),
  )
  row = conn.execute("SELECT auth_user_id FROM leash_users WHERE id = %s", (user_id,)).fetchone()
  if str(row["auth_user_id"]) != str(auth_id):
    raise AuthorityError(403, "User identity binding does not match")


def human_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> Principal:
  token = credential_token(credentials)
  demo_token = os.environ.get("USER_TOKEN", "")
  if demo_token and hmac.compare_digest(token, demo_token):
    if len(demo_token) < 32 or demo_token == os.environ.get("AGENT_TOKEN_SHOPPER"):
      raise AuthorityError(503, "Demo human authentication is misconfigured")
    user_id = os.environ.get("DEMO_USER_ID", "usr_demo")
    try:
      TypeAdapter(UserId).validate_python(user_id)
    except ValueError as exc:
      raise AuthorityError(503, "Demo human identity is misconfigured") from exc
    with get_conn() as conn:
      ensure_user(conn, user_id)
    return Principal("human", user_id)
  user = get_current_user(credentials)
  try:
    user_id = leash_user_id(user.id)
  except ValueError as exc:
    raise AuthorityError(401, "Invalid user identity") from exc
  with get_conn() as conn:
    ensure_user(conn, user_id, user.id)
  return Principal("human", user_id)


def require_human(credentials: Credentials) -> Principal:
  return human_from_credentials(credentials)


def agent_from_token(token: str) -> Principal | None:
  with get_conn() as conn:
    row = conn.execute(
      "SELECT id, user_id, allowed_modes FROM leash_agents WHERE token_sha256 = %s AND enabled",
      (token_digest(token),),
    ).fetchone()
    if row is None:
      scoped = conn.execute("""SELECT r.id AS run_id,r.agent_id,r.user_id,r.registration
        FROM run_credentials c JOIN agent_runs r ON r.id=c.run_id
        JOIN leash_agents a ON a.id=r.agent_id AND a.enabled
        WHERE c.token_sha256=%s AND c.expires_at>now()""", (token_digest(token),)).fetchone()
      if scoped:
        return Principal("agent", scoped["user_id"], scoped["agent_id"],
                         (scoped["registration"]["agent_mode"],), scoped["run_id"])
  if row is None:
    return None
  return Principal("agent", row["user_id"], row["id"], tuple(row["allowed_modes"]))


def require_agent(credentials: Credentials, request: Request) -> Principal:
  principal = agent_from_token(credential_token(credentials))
  if principal is None:
    raise AuthorityError(401, "Invalid or disabled agent credential")
  if principal.delegated_run:
    path = request.url.path
    permitted = (path.startswith(f"/agent-runs/{principal.delegated_run}/execution/")
                 or path == f"/agent-runs/{principal.delegated_run}/control"
                 or path == "/payments" or path.startswith("/payments/")
                 or path in {"/provenance", "/workflow-events"})
    if not permitted:
      raise AuthorityError(403, "Temporary worker credential cannot access this operation")
  return principal


def require_reader(credentials: Credentials) -> Principal:
  token = credential_token(credentials)
  principal = agent_from_token(token)
  return principal if principal is not None else human_from_credentials(credentials)


def bind_agent(conn, *, user_id: str, agent_id: str, token: str, modes: tuple[str, ...]) -> None:
  """Operator-only provisioning; no HTTP route accepts client-selected ownership."""
  from psycopg.types.json import Jsonb

  TypeAdapter(UserId).validate_python(user_id)
  TypeAdapter(AgentId).validate_python(agent_id)
  if len(token) < 32 or token == os.environ.get("USER_TOKEN"):
    raise AuthorityError(422, "Agent credential must be distinct and at least 32 characters")
  if len(set(modes)) != 1 or set(modes) - {"live", "scripted"}:
    raise AuthorityError(422, "Bind each credential to exactly one live or scripted mode")
  if conn.execute("SELECT id FROM leash_users WHERE id = %s", (user_id,)).fetchone() is None:
    raise AuthorityError(404, "Provision the human identity first")
  # Serialize provisioning so ownership never moves via token rotation.
  conn.execute("SELECT pg_advisory_xact_lock(781202603)")
  old = conn.execute("SELECT user_id FROM leash_agents WHERE id = %s", (agent_id,)).fetchone()
  if old is not None and old["user_id"] != user_id:
    raise AuthorityError(409, "Agent is already bound to another human")
  conn.execute(
    """INSERT INTO leash_agents (id, user_id, token_sha256, allowed_modes)
    VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE
    SET token_sha256 = excluded.token_sha256, allowed_modes = excluded.allowed_modes, enabled = true""",
    (agent_id, user_id, token_digest(token), Jsonb(list(dict.fromkeys(modes)))),
  )
