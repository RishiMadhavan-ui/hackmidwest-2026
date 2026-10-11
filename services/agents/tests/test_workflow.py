"""Real installed Graph scheduler; deterministic I/O fixtures, not live proof."""

import asyncio
from copy import deepcopy

import pytest
from strands.multiagent.graph import Graph

from shopper.workflow import Limits, PurchaseWorkflow, WorkflowStopped


class FixturePorts:
  def __init__(self, decisions=None):
    self.events, self.saved, self.contexts = [], [], []
    self.decisions = decisions or [
      {"id": "pay_bad", "status": "blocked", "pre_payment": True,
       "reasons": ["subscription_prohibited"]},
      {"id": "pay_good", "status": "approved", "verified": True, "reasons": []},
    ]
    self.stopped, self.paid, self.investigated = False, 0, 0
    self.mandate = {"id": "mnd_1", "version": 1, "canonical_payload_hash": "a" * 64,
                    "description": "Buy a USB-C charger under $40; no subscriptions."}

  async def check(self):
    if self.stopped:
      raise WorkflowStopped("run_cancelled")

  async def authority(self):
    await self.check()
    return deepcopy(self.mandate)

  async def shop(self, state):
    self.contexts.append(deepcopy(state.checkpoint()))
    return {"sku": "SUB-CARE-MO" if state.attempt == 1 else "CHG-65W",
            "checkout_id": f"chk_{state.attempt}", "source_urls": [f"https://store/{state.attempt}"],
            "source_hashes": [str(state.attempt) * 64]}

  async def verify(self, state):
    return self.decisions[min(state.attempt - 1, len(self.decisions) - 1)]

  async def investigate(self, state):
    self.investigated += 1

  async def pay(self, state):
    self.paid += 1
    return "authorized"

  async def save(self, state):
    self.saved.append(deepcopy(state.checkpoint()))

  def emit(self, phase, **data):
    self.events.append({"phase": phase, **deepcopy(data)})

  def cancel(self):
    self.stopped = True


def test_actual_graph_block_investigate_quarantine_recover_and_authorize():
  ports = FixturePorts()
  workflow = PurchaseWorkflow("run_test", ports)
  assert isinstance(workflow.graph, Graph)
  state = asyncio.run(workflow.run())
  assert state.outcome == "authorized"
  assert state.attempt == 2 and ports.paid == ports.investigated == 1
  assert [e["node"] for e in ports.events if e["phase"] == "node.started"] == [
    "authority", "shopping", "verification", "investigation", "recovery", "shopping",
    "verification", "payment", "terminal",
  ]
  assert ports.contexts[1]["exclusions"]["skus"] == ["SUB-CARE-MO"]
  assert ports.contexts[1]["exclusions"]["source_hashes"] == ["1" * 64]
  assert ports.mandate["version"] == 1
  assert any(s["financial_attempted"] and s["payment_id"] is None for s in ports.saved)


@pytest.mark.parametrize("decision", [
  {"status": "error"}, {"status": "pending_user"}, {"status": "denied"},
  {"status": "approved"}, {"status": "blocked", "reasons": ["subscription_prohibited"]},
  {"status": "authorized"},
])
def test_ambiguous_or_nonrecoverable_decision_never_retries(decision):
  ports = FixturePorts([decision])
  state = asyncio.run(PurchaseWorkflow("run_test", ports).run())
  assert state.attempt == 1
  assert ports.paid == ports.investigated == 0
  assert state.outcome in {"reconciling", "declined"}


@pytest.mark.parametrize("reason", ["financial_authority_unavailable", "checkout_source_unavailable_or_wrong_owner", "unrecognized_code"])
def test_unavailable_evidence_or_authority_is_terminal(reason):
  ports = FixturePorts([{"status": "blocked", "pre_payment": True, "reasons": [reason]}])
  state = asyncio.run(PurchaseWorkflow("run_test", ports).run())
  assert state.outcome == "blocked" and state.attempt == 1
  assert ports.investigated == 1 and ports.paid == 0


def test_candidate_budget_terminates_cycle():
  ports = FixturePorts([{"status": "blocked", "pre_payment": True, "reasons": ["subscription_prohibited"]}])
  state = asyncio.run(PurchaseWorkflow("run_test", ports, Limits(candidates=2)).run())
  assert state.outcome == "blocked" and state.attempt == 2
  assert ports.paid == 0


def test_stop_after_verification_prevents_payment():
  ports = FixturePorts([{"status": "approved", "verified": True}])
  original = ports.verify
  async def verify(state):
    decision = await original(state)
    ports.stopped = True
    return decision
  ports.verify = verify
  workflow = PurchaseWorkflow("run_test", ports)
  with pytest.raises(WorkflowStopped):
    asyncio.run(workflow.run())
  assert ports.paid == 0
  assert workflow.state.outcome == "reconciling"


def test_transport_timeout_does_not_buy_an_alternative():
  ports = FixturePorts()
  async def timeout(state):
    raise TimeoutError()
  ports.verify = timeout
  workflow = PurchaseWorkflow("run_test", ports)
  with pytest.raises((TimeoutError, WorkflowStopped)):
    asyncio.run(workflow.run())
  assert workflow.state.outcome == "reconciling"
  assert workflow.state.attempt == 1 and ports.paid == 0


def test_whole_graph_deadline_cancels_active_node():
  ports = FixturePorts()
  exited = []
  async def slow(state):
    try:
      await asyncio.sleep(10)
    finally:
      exited.append(True)
  ports.shop = slow
  workflow = PurchaseWorkflow("run_test", ports, Limits(total_seconds=.05))
  with pytest.raises(TimeoutError):
    asyncio.run(workflow.run())
  assert exited == [True]
  assert ports.stopped and ports.paid == 0


@pytest.mark.parametrize("financial, expected", [(True, "reconciling"), (False, "stopped")])
def test_final_checkpoint_rejection_preserves_financial_uncertainty(financial, expected):
  ports = FixturePorts()
  workflow = PurchaseWorkflow("run_test", ports)
  async def failing_shop(state):
    state.financial_attempted = financial
    ports.stopped = True
    raise WorkflowStopped("run_cancelled")
  async def save(state):
    if ports.stopped:
      raise WorkflowStopped("execution_scope_rejected")
  ports.shop, ports.save = failing_shop, save
  with pytest.raises(WorkflowStopped) as caught:
    asyncio.run(workflow.run())
  assert caught.value.outcome == expected
  assert workflow.state.outcome == expected and ports.paid == 0

