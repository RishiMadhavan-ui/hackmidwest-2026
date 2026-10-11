import os

import pytest
from pydantic import BaseModel
from strands import Agent, tool

from leash_shared.llm import ROLE_SETTINGS, make_model, configured_provider

ALL_ENV = ("INFERENCE_BASE_URL", "INFERENCE_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY")


@pytest.fixture
def clean_env(monkeypatch):
  for name in (*ALL_ENV, "MODEL_ID", "CHAT_MODEL"):
    monkeypatch.delenv(name, raising=False)


@pytest.fixture
def inference_env(clean_env, monkeypatch):
  monkeypatch.setenv("INFERENCE_BASE_URL", "https://inference.invalid/v1")
  monkeypatch.setenv("INFERENCE_API_KEY", "test-key")


@pytest.mark.parametrize("role", ["guardian", "shopper"])
def test_every_role_sets_max_tokens(inference_env, role):
  config = make_model(role).get_config()
  assert config["model_id"] == "hackathon-chat"
  assert config["params"]["max_tokens"] == ROLE_SETTINGS[role]["max_tokens"]


def test_guardian_is_deterministic(inference_env):
  assert make_model("guardian").get_config()["params"]["temperature"] == 0


def test_model_id_comes_from_env(inference_env, monkeypatch):
  monkeypatch.setenv("MODEL_ID", "other-model")
  assert make_model("shopper").get_config()["model_id"] == "other-model"


def test_provider_metadata_does_not_claim_akamai_for_other_or_missing_endpoint(clean_env, monkeypatch):
  assert configured_provider() == "unconfigured"
  monkeypatch.setenv("OPENAI_BASE_URL", "https://other.invalid/v1")
  monkeypatch.setenv("OPENAI_API_KEY", "test-key")
  assert configured_provider() == "configured-openai-compatible"
  monkeypatch.setenv("OPENAI_BASE_URL", "https://ws.akamai-workshops.com/v1")
  assert configured_provider() == "akamai-inference"


def test_missing_key_fails_without_echoing_secrets(clean_env, monkeypatch):
  monkeypatch.setenv("INFERENCE_BASE_URL", "https://inference.invalid/v1")
  with pytest.raises(RuntimeError, match="INFERENCE_API_KEY is not set"):
    make_model("guardian")


def test_workshop_starter_names_work_as_a_pair(clean_env, monkeypatch):
  monkeypatch.setenv("OPENAI_BASE_URL", "https://ws.invalid/v1")
  monkeypatch.setenv("OPENAI_API_KEY", "starter-key")
  monkeypatch.setenv("CHAT_MODEL", "hackathon-chat")
  model = make_model("shopper")
  assert model.client_args == {"base_url": "https://ws.invalid/v1", "api_key": "starter-key",
                               "timeout": 20.0, "max_retries": 0}
  assert model.get_config()["model_id"] == "hackathon-chat"


def test_names_are_never_mixed_across_providers(clean_env, monkeypatch):
  # An unrelated OpenAI key must not be sent to the Akamai endpoint.
  monkeypatch.setenv("INFERENCE_BASE_URL", "https://ws.invalid/v1")
  monkeypatch.setenv("OPENAI_API_KEY", "someone-elses-key")
  with pytest.raises(RuntimeError, match="INFERENCE_API_KEY is not set"):
    make_model("guardian")


def test_nothing_configured(clean_env):
  with pytest.raises(RuntimeError, match="INFERENCE_BASE_URL is not set"):
    make_model("guardian")


def test_unknown_role_rejected(inference_env):
  with pytest.raises(ValueError):
    make_model("attacker")


# Live smoke test against Akamai inference: one tool call plus one structured
# output, the two things the shopper and guardian depend on.

_live_skip = pytest.mark.skipif(
  not (
    (os.environ.get("INFERENCE_API_KEY") and os.environ.get("INFERENCE_BASE_URL"))
    or (os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"))
  ),
  reason="no inference endpoint configured (INFERENCE_* or OPENAI_* pair)",
)


def live(test):
  # live_inference lets conftest leave the real endpoint settings in place.
  return pytest.mark.live_inference(_live_skip(test))


@tool
def room_price(hotel: str) -> int:
  """Look up tonight's room price in integer cents for a hotel."""
  return 15800


class Room(BaseModel):
  hotel: str
  price_cents: int


@live
def test_live_tool_call():
  agent = Agent(model=make_model("shopper"), tools=[room_price], callback_handler=None)
  agent("Use the room_price tool to look up the price at Crossroads Hotel, then tell me.")
  assert agent.event_loop_metrics.tool_metrics["room_price"].call_count >= 1


@live
def test_live_structured_output():
  agent = Agent(model=make_model("guardian"), callback_handler=None)
  result = agent(
    "Crossroads Hotel charges $158.00 tonight. Report the hotel and the price in cents.",
    structured_output_model=Room,
  )
  room = result.structured_output
  assert isinstance(room, Room)
  assert room.price_cents == 15800
  assert "crossroads" in room.hotel.lower()
