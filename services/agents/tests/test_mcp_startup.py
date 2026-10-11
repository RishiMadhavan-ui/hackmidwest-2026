"""Startup uses mocked MCP I/O and real lease polling; no deployed proof."""
import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
import strands.tools.mcp

from provenance.sink import MemorySink
from shopper import control as control_module, workflow
from shopper.runs import StartRun, _run_graph
from shopper.workflow import WorkflowStopped


def setup(monkeypatch, *, stop=False):
  monkeypatch.setenv("API_URL", "http://api.test")
  monkeypatch.setenv("STORE_MCP_TOKEN", "fixture-store-token")
  calls, controls = [], []
  heartbeat = threading.Event()
  original = control_module.ExecutionControl
  def factory(url, token, run_id):
    def respond(request):
      calls.append((request.url.path, json.loads(request.content)))
      if request.url.path.endswith("heartbeat"):
        heartbeat.set()
      control = controls[0]
      return httpx.Response(200, json={
        "protocol": "execution-v1", "run_id": run_id, "worker_id": control.worker_id,
        "generation": 1, "authority_current": True, "cancel_requested": stop and heartbeat.is_set(),
        "human_launch_verified": True, "financial_state": "unspent", "lease_seconds": 5,
        "mcp_scope_enforced": True, "scope_tokens": {"mcp-leash": "l"*32, "mcp-store": "s"*32},
      })
    client = httpx.AsyncClient(base_url=url, transport=httpx.MockTransport(respond))
    control = original(url, token, run_id, client=client, poll_seconds=.01)
    controls.append(control)
    return control
  monkeypatch.setattr(control_module, "ExecutionControl", factory)
  req = StartRun(task="buy charger", mandate_id="mnd_1", run_id="run_1", launch_id="launch_1",
    agent_id="agt_1", agent_credential="a"*32)
  return req, calls, controls, heartbeat


def test_blocking_mcp_startup_keeps_lease_heartbeats_running(monkeypatch):
  req, calls, controls, heartbeat = setup(monkeypatch)
  closed, entered = [], []
  class MCP:
    def __init__(self, **kwargs): self.url = kwargs["url"]
    def __enter__(self):
      # Requires the owning loop to run while synchronous startup is blocked.
      assert heartbeat.wait(1), "Lease polling was blocked by synchronous MCP startup"
      entered.append(self.url)
      return self
    def list_tools_sync(self): return []
    def __exit__(self, *args): closed.append(self.url)
  class Graph:
    def __init__(self, *args, **kwargs): pass
    async def run(self): return SimpleNamespace(outcome="no_candidate")
  monkeypatch.setattr(strands.tools.mcp, "MCPClient", MCP)
  monkeypatch.setattr(workflow, "PurchaseWorkflow", Graph)
  assert asyncio.run(_run_graph("run_1", req, [])) == "no_candidate"
  assert len(entered) == len(closed) == 2
  assert controls[0].client.is_closed
  assert any(path.endswith("heartbeat") for path, _ in calls)


def test_startup_failure_persists_safe_terminal_reason_without_a_purchase(monkeypatch):
  req, calls, controls, _ = setup(monkeypatch)
  class MCP:
    def __init__(self, **kwargs): pass
    def __enter__(self): raise RuntimeError("Authorization: Bearer private-secret")
  monkeypatch.setattr(strands.tools.mcp, "MCPClient", MCP)
  trace = MemorySink()
  with pytest.raises(WorkflowStopped, match="mcp_leash_startup_failed"):
    asyncio.run(_run_graph("run_1", req, [trace]))
  saved = [body["progress"] for path, body in calls if path.endswith("checkpoint")]
  assert saved[0]["finished"] is True
  assert saved[0]["attempt"] == 0 and saved[0]["financial_attempted"] is False
  assert saved[0]["reasons"] == ["mcp_leash_startup_failed"]
  assert "private-secret" not in json.dumps(trace.events)
  assert controls[0].client.is_closed


def test_stop_during_mcp_startup_never_constructs_graph(monkeypatch):
  req, calls, controls, heartbeat = setup(monkeypatch, stop=True)
  class MCP:
    def __init__(self, **kwargs): pass
    def __enter__(self): assert heartbeat.wait(1); return self
    def list_tools_sync(self): return []
    def __exit__(self, *args): pass
  def forbidden(*args, **kwargs): raise AssertionError("Graph started after stop")
  monkeypatch.setattr(strands.tools.mcp, "MCPClient", MCP)
  monkeypatch.setattr(workflow, "PurchaseWorkflow", forbidden)
  with pytest.raises(WorkflowStopped, match="execution_scope_invalid_or_stopped"):
    asyncio.run(_run_graph("run_1", req, []))
  assert controls[0].client.is_closed
  assert all("payments" not in path for path, _ in calls)
