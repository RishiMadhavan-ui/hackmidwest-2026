"""The one place Leash constructs models.

Every agent gets its model from make_model() so endpoint, auth, and token
limits stay consistent. Never build an OpenAIModel anywhere else.
"""

import os
from urllib.parse import urlsplit
from typing import Any, Literal

from strands.models.openai import OpenAIModel

Role = Literal["guardian", "shopper"]

# Akamai inference defaults to 512 output tokens when max_tokens is missing,
# which truncates JSON mid-object and breaks parsing. Always set it here.
# The guardian runs at temperature 0 so the same cart gets the same verdict.
ROLE_SETTINGS: dict[str, dict[str, Any]] = {
  "guardian": {"temperature": 0.0, "max_tokens": 1024},
  "shopper": {"temperature": 0.3, "max_tokens": 1024},
}

DEFAULT_MODEL_ID = "hackathon-chat"

# The spec names (INFERENCE_*) come first. Cameron's .env.example uses the
# Akamai workshop starter's names (OPENAI_*), so those work too, but only as a
# matched pair: a stray OPENAI_API_KEY for some other provider must never be
# sent to an INFERENCE_BASE_URL endpoint, or the reverse.
_ENV_PAIRS = (
  ("INFERENCE_BASE_URL", "INFERENCE_API_KEY"),
  ("OPENAI_BASE_URL", "OPENAI_API_KEY"),
)


def model_id() -> str:
  return os.environ.get("MODEL_ID") or os.environ.get("CHAT_MODEL") or DEFAULT_MODEL_ID


def _endpoint() -> tuple[str, str]:
  for url_name, key_name in _ENV_PAIRS:
    base_url, api_key = os.environ.get(url_name), os.environ.get(key_name)
    if base_url or api_key:
      # Name the missing variable but never echo a value, so secrets stay out of logs.
      if not base_url:
        raise RuntimeError(f"{url_name} is not set")
      if not api_key:
        raise RuntimeError(f"{key_name} is not set")
      return base_url, api_key
  raise RuntimeError("INFERENCE_BASE_URL is not set")


def configured_provider() -> str:
  """Configuration attribution only; this never claims a successful inference."""
  try:
    base_url, _ = _endpoint()
    host = urlsplit(base_url).hostname
  except (RuntimeError, ValueError):
    return "unconfigured"
  if host == "ws.akamai-workshops.com":
    return "akamai-inference"
  return "configured-openai-compatible"


def make_model(role: Role) -> OpenAIModel:
  """Return a Strands OpenAIModel pointed at Akamai inference for this role.

  The endpoint is text only. Don't send images through these models.
  """
  if role not in ROLE_SETTINGS:
    raise ValueError(f"unknown model role {role!r}, expected one of {sorted(ROLE_SETTINGS)}")

  base_url, api_key = _endpoint()
  return OpenAIModel(
    # Bound transport time and disable invisible client retries. The Graph
    # owns retry/cost budgets and records every actual model attempt.
    client_args={"base_url": base_url, "api_key": api_key, "timeout": 20.0, "max_retries": 0},
    model_id=model_id(),
    params=dict(ROLE_SETTINGS[role]),
  )
