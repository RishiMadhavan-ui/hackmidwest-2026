"""Client protocol tests. Mock API is not proof of SQL or Kubernetes fencing."""

import asyncio
import json
import time

import httpx
import pytest

from shopper.control import ExecutionControl
from shopper.workflow import WorkflowStopped


def fixture(handler=None):
  control = None
  def respond(request):
    body = {
      "protocol": "execution-v1", "run_id": "run_1", "worker_id": control.worker_id,
      "generation": 1, "authority_current": True, "cancel_requested": False,
      "human_launch_verified": True, "financial_state": "unspent", "lease_seconds": 5,
    }
    return handler(request, body) if handler else httpx.Response(200, json=body)
  client = httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(respond))
  control = ExecutionControl("http://api.test", "fixture", "run_1", client=client, poll_seconds=.01)
  return control


def test_claim_and_check_exact_worker_generation():
  sent = []
  def handler(request, body):
    sent.append(json.loads(request.content))
    return httpx.Response(200, json=body)
  async def run():
    control = fixture(handler)
    try:
      await control.claim("launch_1")
      await control.check()
      assert control.generation == 1
      assert sent[1] == {"worker_id": control.worker_id, "generation": 1}
    finally:
      await control.close()
  asyncio.run(run())


@pytest.mark.parametrize("change", [
  {"cancel_requested": True}, {"authority_current": False}, {"generation": 2},
  {"worker_id": "old_worker"}, {"run_id": "other_run"}, {"lease_seconds": 0},
  {"human_launch_verified": False}, {"financial_state": "unknown"},
  {"financial_state": "unexpected"}, {"generation": True}, {"protocol": "old"},
])
def test_stop_stale_generation_unknown_or_missing_authority_latches(change):
  def handler(request, body):
    if request.url.path.endswith("heartbeat"):
      body.update(change)
    return httpx.Response(200, json=body)
  async def run():
    control = fixture(handler)
    try:
      await control.claim("launch_1")
      with pytest.raises(WorkflowStopped):
        await control.check()
      assert control.cancel_signal.is_set()
      with pytest.raises(WorkflowStopped):
        await control.check()
    finally:
      await control.close()
  asyncio.run(run())


def test_old_backend_never_falls_back_to_local_lock_or_registers_new_run():
  async def run():
    paths = []
    def handler(request, body):
      paths.append(request.url.path)
      return httpx.Response(404)
    control = fixture(handler)
    try:
      with pytest.raises(WorkflowStopped, match="execution_backend_unavailable"):
        await control.claim("launch_1")
      assert paths == ["/agent-runs/run_1/execution/claim"]
    finally:
      await control.close()
  asyncio.run(run())


def test_polling_cancels_attached_agent_without_new_node():
  class Agent:
    cancelled = False
    def cancel(self):
      self.cancelled = True
  async def run():
    def handler(request, body):
      if request.url.path.endswith("heartbeat"):
        body["cancel_requested"] = True
      return httpx.Response(200, json=body)
    control, agent = fixture(handler), Agent()
    try:
      await control.claim("launch_1")
      control.attach(agent)
      for _ in range(50):
        if agent.cancelled:
          break
        await asyncio.sleep(.01)
      assert agent.cancelled and control.cancel_signal.is_set()
    finally:
      await control.close()
  asyncio.run(run())


def test_expired_worker_cannot_renew_even_if_backend_later_responds():
  async def run():
    control = fixture()
    try:
      await control.claim("launch_1")
      control.lease_deadline = time.monotonic() - 1
      with pytest.raises(WorkflowStopped, match="expired"):
        await control.check()
    finally:
      await control.close()
  asyncio.run(run())


def test_control_outage_cancels_instead_of_spending_with_cached_permission():
  def handler(request, body):
    if request.url.path.endswith("heartbeat"):
      raise httpx.ConnectError("fixture secret must not leak")
    return httpx.Response(200, json=body)
  async def run():
    control = fixture(handler)
    try:
      await control.claim("launch_1")
      with pytest.raises(WorkflowStopped, match="execution_control_unavailable"):
        await control.check()
      assert control.cancel_signal.is_set()
    finally:
      await control.close()
  asyncio.run(run())
