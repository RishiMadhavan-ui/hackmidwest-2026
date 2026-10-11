"""Human JWT/demo credentials and explicitly provisioned agent ownership."""

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
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
    return None
  return Principal("agent", row["user_id"], row["id"], tuple(row["allowed_modes"]))


def require_agent(credentials: Credentials) -> Principal:
  principal = agent_from_token(credential_token(credentials))
  if principal is None:
    raise AuthorityError(401, "Invalid or disabled agent credential")
  return principal


def require_reader(credentials: Credentials) -> Principal:
  token = credential_token(credentials)
  principal = agent_from_token(token)
  return principal if principal is not None else human_from_credentials(credentials)


def bind_agent(
  conn,
  *,
  user_id: str,
  agent_id: str,
  token: str,
  modes: tuple[str, ...],
  allow_owner_transfer: bool = False,
) -> None:
  """Operator-only provisioning; no HTTP route accepts client-selected ownership.

  allow_owner_transfer is only for demo idle-rebind of cluster shopper tokens.
  """
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
  if old is not None and old["user_id"] != user_id and not allow_owner_transfer:
    raise AuthorityError(409, "Agent is already bound to another human")
  conn.execute(
    """INSERT INTO leash_agents (id, user_id, token_sha256, allowed_modes)
    VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE
    SET user_id = excluded.user_id, token_sha256 = excluded.token_sha256,
        allowed_modes = excluded.allowed_modes, enabled = true""",
    (agent_id, user_id, token_digest(token), Jsonb(list(dict.fromkeys(modes)))),
  )


_CLUSTER_SHOPPER = {
  "live": ("AGENT_TOKEN_SHOPPER", "agt_shopper"),
  "scripted": ("AGENT_TOKEN_SHOPPER_SCRIPTED", "agt_shopper_scripted"),
}


def demo_rebind_enabled() -> bool:
  return os.getenv("LEASH_DEMO_REBIND", "").strip().lower() in ("1", "true", "yes")


def user_has_active_shopper_run(conn, user_id: str) -> bool:
  """True when this human still owns a non-terminal, uncancelled, unexpired launch."""
  return conn.execute(
    """SELECT 1 FROM run_executions e
       JOIN agent_runs r ON r.id = e.run_id
       WHERE r.user_id = %s AND e.state != 'terminal' AND e.deadline > now()
         AND NOT EXISTS (SELECT 1 FROM run_cancellations c WHERE c.run_id = e.run_id)
       LIMIT 1""",
    (user_id,),
  ).fetchone() is not None


def ensure_cluster_shopper(conn, user_id: str, mode: str) -> str:
  """Return the agents-pod shopper id for this human and mode, binding if free.

  Mission Control drafts often use a live UI agent. Scripted Start shopping still
  needs the AGENT_TOKEN_SHOPPER_SCRIPTED row so the worker can claim the launch.

  With LEASH_DEMO_REBIND=1, an idle cluster credential may move to another human
  so multiple demo accounts can take turns. Concurrent shopping still fails closed.
  """
  if mode not in _CLUSTER_SHOPPER:
    raise AuthorityError(422, "Shopper mode must be live or scripted")
  env_name, default_id = _CLUSTER_SHOPPER[mode]
  token = os.getenv(env_name, "").strip()
  if len(token) < 32:
    raise AuthorityError(503, f"Shopping start requires {env_name} on the API")
  owned = conn.execute(
    "SELECT id, user_id, enabled, allowed_modes FROM leash_agents WHERE token_sha256 = %s",
    (token_digest(token),),
  ).fetchone()
  if owned is not None:
    owner = str(owned["user_id"])
    agent_id = str(owned["id"])
    if owner != user_id:
      if not demo_rebind_enabled():
        raise AuthorityError(
          409,
          f"{env_name} is bound to another human; an operator must rebind it",
        )
      if user_has_active_shopper_run(conn, owner):
        raise AuthorityError(
          409,
          f"{env_name} is in use by another human's active shopping run; try again when it finishes",
        )
      bind_agent(
        conn,
        user_id=user_id,
        agent_id=agent_id,
        token=token,
        modes=(mode,),
        allow_owner_transfer=True,
      )
      return agent_id
    if not owned["enabled"] or list(owned["allowed_modes"]) != [mode]:
      bind_agent(
        conn, user_id=user_id, agent_id=agent_id, token=token, modes=(mode,),
      )
    return agent_id

  agent_id = default_id
  taken = conn.execute(
    "SELECT user_id FROM leash_agents WHERE id = %s", (agent_id,),
  ).fetchone()
  if taken is not None and str(taken["user_id"]) != user_id:
    if demo_rebind_enabled() and not user_has_active_shopper_run(conn, str(taken["user_id"])):
      bind_agent(
        conn,
        user_id=user_id,
        agent_id=agent_id,
        token=token,
        modes=(mode,),
        allow_owner_transfer=True,
      )
      return agent_id
    agent_id = "agt_" + mode + "_" + user_id.removeprefix("usr_")[:16]
  bind_agent(conn, user_id=user_id, agent_id=agent_id, token=token, modes=(mode,))
  return agent_id
