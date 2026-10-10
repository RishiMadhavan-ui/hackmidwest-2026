"""A Strands model that replays a fixed script of tool calls.

FIXTURE ONLY. It drives the real Strands event loop, tools, and hooks without
a live model, so tests are repeatable. A run driven by this model is never a
genuine agent trace and must not be presented as one.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from strands.models.model import Model


class ScriptedModel(Model):
  def __init__(self, turns: list[list[tuple[str, dict[str, Any]]] | str]) -> None:
    # Each turn is either a list of (tool_name, input) calls or final text.
    self.turns = list(turns)
    self.calls = 0

  def update_config(self, **model_config: Any) -> None:
    pass

  def get_config(self) -> dict[str, Any]:
    return {"model_id": "scripted-fixture"}

  async def structured_output(self, *args: Any, **kwargs: Any):
    raise NotImplementedError("ScriptedModel does not do structured output")
    yield  # pragma: no cover

  async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncIterator:
    turn = self.turns[self.calls] if self.calls < len(self.turns) else "done"
    self.calls += 1
    yield {"messageStart": {"role": "assistant"}}
    if isinstance(turn, str):
      yield {"contentBlockStart": {"start": {}}}
      yield {"contentBlockDelta": {"delta": {"text": turn}}}
      yield {"contentBlockStop": {}}
      yield {"messageStop": {"stopReason": "end_turn"}}
      return
    for i, (name, tool_input) in enumerate(turn):
      tool_use_id = f"tool_{self.calls}_{i}"
      yield {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": tool_use_id}}}}
      yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
      yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}
