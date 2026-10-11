"""Bounded SDK Graph. Ports are authenticated I/O, never model-authored decisions.

Only safe summaries cross Graph edges. In particular the SDK's concatenated
upstream input is deliberately ignored: it must not seed a recovery transcript.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, Status


@dataclass(frozen=True)
class Limits:
  candidates: int = 3
  nodes: int = 20
  node_seconds: float = 45.0
  total_seconds: float = 150.0
  model_calls: int = 18
  input_tokens: int = 60000
  tool_calls: int = 30


class WorkflowStopped(RuntimeError):
  """A safe, public reason code; never include an HTTP body or model text."""
  def __init__(self, reason: str, outcome: str | None = None):
    super().__init__(reason)
    self.outcome = outcome


@dataclass
class State:
  run_id: str
  mandate: dict[str, Any] = field(default_factory=dict)
  attempt: int = 0
  candidate: dict[str, Any] | None = None
  decision: dict[str, Any] = field(default_factory=dict)
  exclusions: dict[str, list[str]] = field(
    default_factory=lambda: {"skus": [], "checkouts": [], "source_hashes": [], "source_urls": []}
  )
  reasons: list[str] = field(default_factory=list)
  outcome: str = "running"
  next_node: str = "authority"
  financial_attempted: bool = False
  finished: bool = False
  started: float = field(default_factory=time.monotonic)

  def checkpoint(self) -> dict[str, Any]:
    # No prompts, transcripts, raw pages, card credentials or model explanations.
    return {
      "attempt": self.attempt, "node": self.next_node, "outcome": self.outcome,
      "exclusions": self.exclusions, "reasons": self.reasons,
      "checkout_id": (self.candidate or {}).get("checkout_id"),
      "payment_id": self.decision.get("id"),
      "financial_attempted": self.financial_attempted,
      "finished": self.finished,
    }


class Ports(Protocol):
  async def check(self) -> None: ...
  async def authority(self) -> dict[str, Any]: ...
  async def shop(self, state: State) -> dict[str, Any] | None: ...
  async def verify(self, state: State) -> dict[str, Any]: ...
  async def investigate(self, state: State) -> None: ...
  async def pay(self, state: State) -> str: ...
  async def save(self, state: State) -> None: ...
  def emit(self, phase: str, **data: Any) -> None: ...
  def cancel(self) -> None: ...


# Only known pre-payment product violations permit replacement. Fail closed on
# new reason codes until reviewed. Missing authority/evidence are not a reason
# to keep shopping or repeatedly contact a broken integration.
RECOVERABLE = frozenset({
  "category_mismatch", "product_constraint_unmet",
  "quantity_exceeded", "subscription_prohibited", "recurring_prohibited",
  "amount_over_limit",
  "merchant_not_allowed",
})


class WorkflowNode(MultiAgentBase):
  def __init__(self, owner: "PurchaseWorkflow", name: str):
    super().__init__()
    self.owner, self.id = owner, name

  async def invoke_async(self, task, invocation_state=None, **kwargs):
    await self.owner.step(self.id)
    return MultiAgentResult(status=Status.COMPLETED, execution_count=1)


class PurchaseWorkflow:
  def __init__(self, run_id: str, ports: Ports, limits: Limits | None = None):
    self.ports, self.limits = ports, limits or Limits()
    self.state = State(run_id)
    builder = GraphBuilder()
    names = ("authority", "shopping", "verification", "investigation", "recovery", "payment", "terminal")
    for name in names:
      builder.add_node(WorkflowNode(self, name), name)
    for source, targets in {
      "authority": ("shopping",), "shopping": ("verification", "terminal"),
      "verification": ("investigation", "payment", "terminal"),
      "investigation": ("recovery",), "recovery": ("shopping", "terminal"),
      "payment": ("terminal",),
    }.items():
      for target in targets:
        builder.add_edge(source, target, condition=self._edge(source, target))
    builder.set_entry_point("authority")
    builder.set_max_node_executions(self.limits.nodes)
    builder.set_node_timeout(self.limits.node_seconds)
    builder.set_execution_timeout(self.limits.total_seconds)
    builder.reset_on_revisit(True)
    builder.set_graph_id(run_id)
    self.graph = builder.build()

  def _edge(self, source, target):
    def selected(_):
      chosen = self.state.next_node == target
      # Conditions are pure: the SDK evaluates them while assembling node inputs
      # as well as scheduling. Emit the traversed edge when the next node starts.
      return chosen
    return selected

  async def step(self, name: str) -> None:
    s, p = self.state, self.ports
    await p.check()
    if time.monotonic() - s.started >= self.limits.total_seconds:
      raise WorkflowStopped("execution_deadline")
    p.emit("node.started", node=name, attempt=s.attempt)
    await getattr(self, "_" + name)()
    await p.save(s)
    p.emit("node.completed", node=name, attempt=s.attempt, outcome=s.outcome)
    if name != "terminal":
      await p.check()
      p.emit("edge.traversed", source=name, target=s.next_node, attempt=s.attempt)

  async def _authority(self):
    self.state.mandate = await self.ports.authority()
    self.state.next_node = "shopping"

  async def _shopping(self):
    s = self.state
    if s.attempt >= self.limits.candidates or s.financial_attempted:
      raise WorkflowStopped("candidate_limit_or_financial_barrier")
    s.attempt += 1
    s.candidate = None
    # Persist the attempt before asking any tool to create a checkout.
    await self.ports.save(s)
    s.candidate = await self.ports.shop(s)
    if s.candidate is None:
      s.outcome, s.next_node = "no_candidate", "terminal"
    else:
      if s.candidate["sku"] in s.exclusions["skus"] or s.candidate["checkout_id"] in s.exclusions["checkouts"]:
        raise WorkflowStopped("quarantined_candidate")
      s.next_node = "verification"

  async def _verification(self):
    s = self.state
    # The existing request_payment endpoint verifies AND requests authority.
    # Persist an ambiguity barrier before calling it; a timeout never recovers.
    s.financial_attempted = True
    await self.ports.save(s)
    s.decision = await self.ports.verify(s)
    status = s.decision.get("status")
    if status == "blocked" and s.decision.get("pre_payment") is True:
      s.financial_attempted = False
      s.reasons = s.decision["reasons"]
      s.next_node = "investigation"
    elif status == "approved" and s.decision.get("verified") is True:
      s.next_node = "payment"
    else:
      # pending_user is not autonomous consent; approved is not authorization.
      s.outcome = "declined" if status == "denied" else "reconciling"
      s.next_node = "terminal"
    self.ports.emit("verification.result", attempt=s.attempt, status=status,
                    reasons=s.decision.get("reasons", []), payment_id=s.decision.get("id"))

  async def _investigation(self):
    await self.ports.investigate(self.state)
    self.state.next_node = "recovery"

  async def _recovery(self):
    s = self.state
    candidate = s.candidate or {}
    for key, values in {
      "skus": [candidate.get("sku")], "checkouts": [candidate.get("checkout_id")],
      "source_hashes": candidate.get("source_hashes", []),
      "source_urls": candidate.get("source_urls", []),
    }.items():
      s.exclusions[key] = sorted(set(s.exclusions[key]) | {v for v in values if v})
    self.ports.emit("candidate.quarantined", attempt=s.attempt, exclusions=s.exclusions)
    eligible = bool(s.reasons) and set(s.reasons) <= RECOVERABLE
    if not eligible or s.attempt >= self.limits.candidates or s.financial_attempted:
      s.outcome, s.next_node = "blocked", "terminal"
      return
    # Fresh authority must match the initial immutable confirmed version/hash.
    current = await self.ports.authority()
    if current != s.mandate:
      raise WorkflowStopped("authority_changed")
    s.decision = {}
    s.next_node = "shopping"
    self.ports.emit("recovery.started", attempt=s.attempt + 1, reasons=s.reasons,
                    exclusions=s.exclusions)

  async def _payment(self):
    self.state.outcome = await self.ports.pay(self.state)
    self.state.next_node = "terminal"

  async def _terminal(self):
    self.ports.emit("run.terminal", outcome=self.state.outcome, attempt=self.state.attempt)

  async def run(self) -> State:
    self.ports.emit("graph.started")
    try:
      async with asyncio.timeout(self.limits.total_seconds):
        result = await self.graph.invoke_async("Execute the registered purchase workflow.")
      if self.state.outcome == "running" or result.status != Status.COMPLETED:
        raise WorkflowStopped("graph_incomplete")
    except (asyncio.CancelledError, TimeoutError, WorkflowStopped) as exc:
      self.ports.cancel()
      if self.state.financial_attempted:
        self.state.outcome = "reconciling"
      else:
        self.state.outcome = "cancelled" if isinstance(exc, asyncio.CancelledError) else "stopped"
      self.ports.emit("graph.stopped", outcome=self.state.outcome,
                      reason=str(exc) if isinstance(exc, WorkflowStopped) else type(exc).__name__)
      if isinstance(exc, WorkflowStopped):
        exc.outcome = self.state.outcome
      raise
    except Exception:
      self.ports.cancel()
      self.state.outcome = "reconciling" if self.state.financial_attempted else "failed"
      self.ports.emit("graph.failed", outcome=self.state.outcome)
      raise WorkflowStopped("graph_execution_failed", self.state.outcome) from None
    finally:
      # Durable evidence is attempted even after cancellation. The backend may
      # reject a stale lease; it must never resurrect that worker's authority.
      try:
        self.state.finished = True
        await self.ports.save(self.state)
      except Exception:
        self.ports.cancel()
        # Never hide a possibly completed payment behind a generic failure or
        # invite a retry just because its final checkpoint could not be written.
        self.state.outcome = "reconciling" if self.state.financial_attempted else "stopped"
        raise WorkflowStopped("terminal_checkpoint_unavailable", self.state.outcome) from None
    return self.state
