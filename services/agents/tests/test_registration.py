"""A run is registered with the api before it emits any trace event."""

import time

import pytest
import respx

from provenance.outbox import shared_outbox
from shopper.runs import RunManager, StartRun

API = "http://api.test"
LIVE_TOKEN = "live-agent-token"
SCRIPTED_TOKEN = "scripted-agent-token"


@pytest.fixture
def api_env(monkeypatch):
  monkeypatch.setenv("API_URL", API)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", LIVE_TOKEN)
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER_SCRIPTED", SCRIPTED_TOKEN)


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
  for token, lane in ((LIVE_TOKEN, "live"), (SCRIPTED_TOKEN, "scripted")):
    box = shared_outbox(API, token, lane)
    box.flush(timeout=5)
    assert box.stop(timeout=5)


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
  # A scripted run registers with the scripted credential, never the live one.
  assert body.headers["authorization"] == f"Bearer {SCRIPTED_TOKEN}"
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
    ({"status_code": 201, "json": {"id": None, "agent_mode": "scripted"}}, "different run id"),
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


@pytest.mark.parametrize(
  "echo",
  [
    {},  # no agent_mode at all
    {"agent_mode": None},
    {"agent_mode": "live"},  # the run is scripted
    {"agent_mode": "SCRIPTED"},
  ],
)
def test_registration_must_echo_the_exact_mode(api_env, echo):
  def register(request):
    return respx.MockResponse(201, json={"id": _json(request)["id"], **echo})

  with respx.mock(assert_all_called=False) as mock:
    mock.post(f"{API}/agent-runs").mock(side_effect=register)
    intake = mock.post(f"{API}/provenance").respond(202)
    calls = []
    manager = RunManager(runner=emitting_runner(calls))
    record = wait_done(manager, manager.start(scripted())["id"])
    drain()
  assert record["status"] == "failed"
  assert "agent mode" in record["error"]
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


def test_each_mode_registers_and_traces_with_its_own_credential(api_env):
  def register(request):
    body = _json(request)
    return respx.MockResponse(201, json={"id": body["id"], "agent_mode": body["agent_mode"]})

  with respx.mock() as mock:
    reg = mock.post(f"{API}/agent-runs").mock(side_effect=register)
    intake = mock.post(f"{API}/provenance").respond(202)
    manager = RunManager(runner=emitting_runner([]))
    live = wait_done(manager, manager.start(StartRun(task="t", mandate_id="mnd_live"))["id"])
    fixture = wait_done(manager, manager.start(scripted("mnd_scripted"))["id"])
    drain()

  assert live["status"] == fixture["status"] == "completed"
  by_mode = {_json(c.request)["agent_mode"]: c.request.headers["authorization"] for c in reg.calls}
  assert by_mode == {"live": f"Bearer {LIVE_TOKEN}", "scripted": f"Bearer {SCRIPTED_TOKEN}"}
  traces = {_json(c.request)["run_id"]: c.request.headers["authorization"] for c in intake.calls}
  assert traces == {
    live["id"]: f"Bearer {LIVE_TOKEN}",
    fixture["id"]: f"Bearer {SCRIPTED_TOKEN}",
  }


def test_scripted_run_without_scripted_credential_fails_and_sends_nothing(api_env, monkeypatch):
  monkeypatch.delenv("AGENT_TOKEN_SHOPPER_SCRIPTED")
  with respx.mock(assert_all_called=False) as mock:
    anything = mock.route().respond(201, json={})
    calls = []
    manager = RunManager(runner=emitting_runner(calls))
    record = wait_done(manager, manager.start(scripted())["id"])
  assert record["status"] == "failed"
  assert "AGENT_TOKEN_SHOPPER_SCRIPTED is not set" in record["error"]
  assert LIVE_TOKEN not in record["error"]
  assert calls == []
  # Nothing was sent at all, so the live credential was never used for it.
  assert not anything.called
