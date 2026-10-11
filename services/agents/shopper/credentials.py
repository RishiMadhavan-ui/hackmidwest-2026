"""Which Leash agent credential a run uses: one per mode, never shared.

The api binds every agent credential to exactly one agent id, one human, and
one mode (R02 `bind-agent`). A live run and a scripted run are therefore two
different agents to Leash, each with its own token, its own agent id, and its
own human-confirmed mandates.

There is no fallback between them. A scripted run with no scripted credential
fails; it never borrows the live one, which would record a fixture as live
behavior (or be refused by the api, which checks the mode).
"""

import os
from dataclasses import dataclass
from typing import Literal

Mode = Literal["live", "scripted"]

# (token env var, agent id env var, default agent id). Token names follow the
# api's AGENT_TOKEN_* convention for `manage.py bind-agent --token-env`.
_CREDENTIALS: dict[str, tuple[str, str, str]] = {
  "live": ("AGENT_TOKEN_SHOPPER", "SHOPPER_AGENT_ID", "agt_shopper"),
  "scripted": ("AGENT_TOKEN_SHOPPER_SCRIPTED", "SHOPPER_SCRIPTED_AGENT_ID", "agt_shopper_scripted"),
}


@dataclass(frozen=True)
class AgentCredential:
  mode: Mode
  agent_id: str
  token_env: str
  token: str

  def bearer(self) -> dict[str, str]:
    return {"Authorization": f"Bearer {self.token}"}


class CredentialError(RuntimeError):
  pass


def token_env(mode: Mode) -> str:
  return _CREDENTIALS[mode][0]


def agent_id_for(mode: Mode) -> str:
  _, id_env, default = _CREDENTIALS[mode]
  return os.environ.get(id_env, default)


def credential_for(mode: Mode) -> AgentCredential:
  if mode not in _CREDENTIALS:
    raise CredentialError(f"unknown agent mode {mode!r}")
  env = token_env(mode)
  token = os.environ.get(env)
  # Name the missing variable but never echo a value.
  if not token:
    raise CredentialError(f"{env} is not set; {mode} runs need their own credential")
  other = "scripted" if mode == "live" else "live"
  if token == os.environ.get(token_env(other)):
    raise CredentialError(
      f"{env} must be a separate credential from {token_env(other)}; "
      "each Leash credential is bound to one mode"
    )
  if agent_id_for(mode) == agent_id_for(other):
    raise CredentialError("live and scripted runs need different agent ids")
  return AgentCredential(mode=mode, agent_id=agent_id_for(mode), token_env=env, token=token)
