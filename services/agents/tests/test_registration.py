"""A run is registered with the api before it emits any trace event."""

import time

import pytest
import respx

from provenance.outbox import shared_outbox
from shopper.runs import RunManager, StartRun

API = "http://api.test"


@pytest.fixture
def api_env(monkeypatch):
  monkeypatch.setenv("API_URL", API)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", "agent-token")


def wait_done(manager, run_id):
  for _ in range(200):
    record = manager.get(run_id)
    if record["status"] in ("completed", "failed"):
      return record
    time.sleep(0.02)
  return record


def emitting_runner(calls):
  def runner(run_id, req, sinks):
    calls.append(run_id)
    for sink in sinks:
      sink.emit({"event_id": "evt_1", "type": "agent.tool.before", "run_id": run_id})
    return "done"

  return runner


def scripted(mandate_id="mnd_1"):
  return StartRun(task="t", mandate_id=mandate_id, agent_mode="scripted", sku="CHG-65W")


def drain():
  box = shared_outbox(API, "agent-token")
  box.flush(timeout=5)
  box.stop()


def test_registers_before_any_trace(api_env):
  order = []

  def register(request):
    order.append("register")
    return respx.MockResponse(201, json={"id": _json(request)["id"], "agent_mode": "scripted"})

  def intake(request):
    order.append("trace")
    return respx.MockResponse(202)

  with respx.mock() as mock:
    reg = mock.post(f"{API}/agent-runs").mock(side_effect=register)
    mock.post(f"{API}/provenance").mock(side_effect=intake)

    calls = []
    manager = RunManager(runner=emitting_runner(calls))
    run_id = manager.start(scripted())["id"]
    record = wait_done(manager, run_id)
    drain()

  assert record["status"] == "completed", record["error"]
  assert record["registered"] is True
  assert order == ["register", "trace"]
  body = reg.calls.last.request
  assert body.headers["authorization"] == "Bearer agent-token"
  sent = _json(body)
  assert sent == {
    "id": run_id,
    "mandate_id": "mnd_1",
    "agent_mode": "scripted",
    "model": "scripted-shopper",
    "provider": "fixture",
  }


@pytest.mark.parametrize(
  ("response", "message"),
  [
    ({"status_code": 403, "json": {"detail": "Mandate is not yours"}}, "Mandate is not yours"),
    ({"status_code": 201, "json": {"id": "run_someone_else"}}, "different run id"),
    ({"status_code": 201, "json": {"id": None, "agent_mode": "live"}}, "different"),
  ],
)
def test_failed_registration_stops_the_run_before_any_trace(api_env, response, message):
  with respx.mock(assert_all_called=False) as mock:
    mock.post(f"{API}/agent-runs").respond(**response)
    intake = mock.post(f"{API}/provenance").respond(202)
    calls = []
    manager = RunManager(runner=emitting_runner(calls))
    record = wait_done(manager, manager.start(scripted())["id"])
    drain()
  assert record["status"] == "failed"
  assert message in record["error"]
  assert calls == []
  assert not intake.called


def test_registration_needs_a_mandate(api_env):
  with respx.mock(assert_all_called=False) as mock:
    reg = mock.post(f"{API}/agent-runs").respond(201)
    manager = RunManager(runner=emitting_runner([]))
    record = wait_done(manager, manager.start(StartRun(task="t"))["id"])
  assert record["status"] == "failed"
  assert "mandate_id" in record["error"]
  assert not reg.called


def test_api_unreachable_fails_the_run(api_env):
  import httpx

  with respx.mock(assert_all_called=False) as mock:
    mock.post(f"{API}/agent-runs").mock(side_effect=httpx.ConnectError("down"))
    manager = RunManager(runner=emitting_runner([]))
    record = wait_done(manager, manager.start(scripted())["id"])
  assert record["status"] == "failed"
  assert "unreachable" in record["error"]


def test_local_mode_without_api_skips_registration():
  calls = []
  manager = RunManager(runner=emitting_runner(calls))
  record = wait_done(manager, manager.start(scripted())["id"])
  assert record["status"] == "completed"
  assert record["registered"] is False
  assert len(calls) == 1


def _json(request):
  import json

  return json.loads(request.content)
