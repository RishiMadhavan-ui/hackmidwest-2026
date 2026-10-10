"""Durable trace delivery: spool, retry, order, rejection, and restart recovery."""

import json
import threading

import httpx
import pytest
import respx

from provenance.outbox import OutboxSink

API = "http://api.test"
PAN = "4111111111111111"


def event(n, **extra):
  return {"event_id": f"evt_{n:03d}", "type": "agent.tool.after", "run_id": "run_1", **extra}


@pytest.fixture
def spool(tmp_path):
  return tmp_path / "spool"


def test_delivers_redacted_event_with_agent_bearer_and_clears_spool(spool):
  with respx.mock() as mock:
    route = mock.post(f"{API}/provenance").respond(202)
    box = OutboxSink(API + "/", "agent-token", spool)
    box.emit(event(1, note=f"card {PAN}"))
    assert box.flush(timeout=5)
    assert box.stop(timeout=5)
  request = route.calls.last.request
  assert request.headers["authorization"] == "Bearer agent-token"
  assert PAN not in request.content.decode()
  assert box.pending_count() == 0


def test_nothing_unredacted_ever_touches_disk(spool, monkeypatch):
  box = OutboxSink(API, "t", spool)
  # No worker, so the file stays on disk for us to read.
  monkeypatch.setattr(box, "start", lambda: None)
  box.emit(event(1, card={"number": PAN, "cvv": "321"}, note=f"use {PAN}"))
  on_disk = "".join(p.read_text() for p in spool.rglob("*.json"))
  assert on_disk
  assert PAN not in on_disk and '"321"' not in on_disk


def test_retries_through_an_outage_in_order(spool):
  with respx.mock() as mock:
    route = mock.post(f"{API}/provenance")
    route.side_effect = [
      httpx.ConnectError("api down"),
      httpx.Response(503),
      httpx.Response(202),
      httpx.Response(202),
    ]
    box = OutboxSink(API, "t", spool)
    box.emit(event(1))
    box.emit(event(2))
    assert box.flush(timeout=10)
    assert box.stop(timeout=5)
  sent = [json.loads(c.request.content)["event_id"] for c in route.calls]
  # The head of the line is retried until it lands; order never changes.
  assert sent == ["evt_001", "evt_001", "evt_001", "evt_002"]


def test_permanent_rejection_is_set_aside_not_retried_forever(spool):
  with respx.mock() as mock:
    route = mock.post(f"{API}/provenance")
    route.side_effect = [httpx.Response(422), httpx.Response(202)]
    box = OutboxSink(API, "t", spool)
    box.emit(event(1))
    box.emit(event(2))
    assert box.flush(timeout=5)
    assert box.stop(timeout=5)
  assert [p.name.split("-", 1)[1] for p in (spool / "rejected").glob("*.json")] == ["evt_001.json"]
  assert route.call_count == 2


def test_duplicate_already_stored_counts_as_delivered(spool):
  with respx.mock() as mock:
    mock.post(f"{API}/provenance").respond(409)
    box = OutboxSink(API, "t", spool)
    box.emit(event(1))
    assert box.flush(timeout=5)
    assert box.stop(timeout=5)
  assert not list((spool / "rejected").glob("*.json"))


def api_down_recording(attempted: threading.Event):
  def handler(request):
    attempted.set()
    raise httpx.ConnectError("api down")

  return handler


def test_events_spooled_before_a_restart_are_delivered_after_it(spool):
  # First process: the api is down the whole time, then the process stops.
  # Synchronize on an observed delivery attempt, not on how fast this machine
  # gets there, and make sure the old worker has exited before restarting.
  attempted = threading.Event()
  with respx.mock() as mock:
    mock.post(f"{API}/provenance").mock(side_effect=api_down_recording(attempted))
    first = OutboxSink(API, "t", spool)
    first.emit(event(1))
    first.emit(event(2))
    assert attempted.wait(timeout=10), "the worker never tried to deliver"
    assert first.stop(timeout=10), "the old worker did not exit"
  assert first.pending_count() == 2

  # Next process: same spool, api is back.
  with respx.mock() as mock:
    route = mock.post(f"{API}/provenance").respond(202)
    second = OutboxSink(API, "t", spool)
    assert second.flush(timeout=10)
    assert second.stop(timeout=5)
  assert [json.loads(c.request.content)["event_id"] for c in route.calls] == ["evt_001", "evt_002"]


def test_stop_keeps_unacknowledged_events(spool):
  attempted = threading.Event()
  with respx.mock() as mock:
    mock.post(f"{API}/provenance").mock(side_effect=api_down_recording(attempted))
    box = OutboxSink(API, "t", spool)
    box.emit(event(1))
    assert attempted.wait(timeout=10)
    assert box.stop(timeout=10)
  assert box.pending_count() == 1
  assert not list((spool / "rejected").glob("*.json"))


def test_stop_without_a_worker_is_immediate(spool):
  assert OutboxSink(API, "t", spool).stop(timeout=0)
