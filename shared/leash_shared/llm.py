"""The one place Leash constructs models.

Every agent gets its model from make_model() so endpoint, auth, and token
limits stay consistent. Never build an OpenAIModel anywhere else.
"""

import os
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


def make_model(role: Role) -> OpenAIModel:
  """Return a Strands OpenAIModel pointed at Akamai inference for this role.

  The endpoint is text only. Don't send images through these models.
  """
  if role not in ROLE_SETTINGS:
    raise ValueError(f"unknown model role {role!r}, expected one of {sorted(ROLE_SETTINGS)}")

  base_url = os.environ.get("INFERENCE_BASE_URL")
  api_key = os.environ.get("INFERENCE_API_KEY")
  # Name the missing variable but never echo a value, so secrets stay out of logs.
  if not base_url:
    raise RuntimeError("INFERENCE_BASE_URL is not set")
  if not api_key:
    raise RuntimeError("INFERENCE_API_KEY is not set")

  return OpenAIModel(
    client_args={"base_url": base_url, "api_key": api_key},
    model_id=os.environ.get("MODEL_ID", DEFAULT_MODEL_ID),
    params=dict(ROLE_SETTINGS[role]),
  )
