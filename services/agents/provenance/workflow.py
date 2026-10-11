"""Sanitized execution metadata. No prompts, completion text or reasoning.

Uses agent.step from frozen EventType; intake is the separately versioned
workflow endpoint, not the frozen tool/source-only provenance union.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from strands.hooks import AfterModelCallEvent, BeforeModelCallEvent, HookProvider

from leash_shared.llm import configured_provider, model_id
from provenance.redact import redact
from shopper.workflow import WorkflowStopped


class WorkflowEvents:
  def __init__(self, run_id, agent_id, agent_mode, sinks):
    self.run_id, self.agent_id, self.mode, self.sinks = run_id, agent_id, agent_mode, sinks

  def emit(self, phase: str, **data: Any):
    event = redact({
      "event_id": "evt_" + uuid.uuid4().hex, "type": "agent.step",
      "run_id": self.run_id, "agent_id": self.agent_id, "agent_mode": self.mode,
      "timestamp": datetime.now(UTC).isoformat(),
      "schema_version": 1, "phase": phase, "data": data,
    })
    for sink in self.sinks:
      try:
        sink.emit(event)
      except Exception:
        # A missing durable execution trace is not silently a successful run.
        raise WorkflowStopped("workflow_event_spool_unavailable") from None


class InferenceHooks(HookProvider):
  def __init__(self, events, budget, check, role, *, fixture=None):
    self.events, self.budget, self.check, self.role = events, budget, check, role
    self.started = None
    self.call_id = None
    self.fixture = events.mode == "scripted" if fixture is None else fixture

  def register_hooks(self, registry, **kwargs):
    registry.add_callback(BeforeModelCallEvent, self.before)
    registry.add_callback(AfterModelCallEvent, self.after)

  async def before(self, event):
    await self.check()
    self.budget.model_calls += 1
    projected = event.projected_input_tokens
    if projected is None:
      # A byte count is a conservative bound when the SDK estimator is absent.
      import json
      projected = len(json.dumps(event.agent.messages, ensure_ascii=True))
    self.budget.input_tokens += projected
    if (self.budget.model_calls > self.budget.limits.model_calls
        or self.budget.input_tokens > self.budget.limits.input_tokens):
      raise WorkflowStopped("inference_budget_exhausted")
    self.call_id, self.started = "inf_" + uuid.uuid4().hex, time.monotonic()
    self.events.emit("inference.started", **self._metadata())

  def _metadata(self):
    return {
      "inference_id": self.call_id, "role": self.role,
      "provider": "fixture" if self.fixture else configured_provider(),
      "model": "scripted-fixture" if self.fixture else model_id(),
      "execution": "fixture" if self.fixture else "model_call",
    }

  def after(self, event):
    if self.started is None:
      return
    self.events.emit("inference.failed" if event.exception else "inference.completed",
      **self._metadata(), duration_ms=round((time.monotonic() - self.started) * 1000),
      error=type(event.exception).__name__ if event.exception else None)
    self.started = None
