import os

import pytest
from pydantic import BaseModel
from strands import Agent, tool

from leash_shared.llm import ROLE_SETTINGS, make_model


@pytest.fixture
def inference_env(monkeypatch):
  monkeypatch.setenv("INFERENCE_BASE_URL", "https://inference.invalid/v1")
  monkeypatch.setenv("INFERENCE_API_KEY", "test-key")
  monkeypatch.delenv("MODEL_ID", raising=False)


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


def test_missing_key_fails_without_echoing_secrets(monkeypatch):
  monkeypatch.setenv("INFERENCE_BASE_URL", "https://inference.invalid/v1")
  monkeypatch.delenv("INFERENCE_API_KEY", raising=False)
  with pytest.raises(RuntimeError, match="INFERENCE_API_KEY is not set"):
    make_model("guardian")


def test_unknown_role_rejected(inference_env):
  with pytest.raises(ValueError):
    make_model("attacker")


# Live smoke test against Akamai inference: one tool call plus one structured
# output, the two things the shopper and guardian depend on.

live = pytest.mark.skipif(
  not (os.environ.get("INFERENCE_API_KEY") and os.environ.get("INFERENCE_BASE_URL")),
  reason="INFERENCE_API_KEY and INFERENCE_BASE_URL not set",
)


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
