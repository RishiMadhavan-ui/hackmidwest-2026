"""Workflow spool delivery and real model-hook metadata, without live inference."""

import json

import respx

from provenance.outbox import OutboxSink
from provenance.workflow import WorkflowEvents


def test_workflow_events_route_separately_and_replay_after_restart(tmp_path, monkeypatch):
  first = OutboxSink("http://api.test", "fixture", tmp_path)
  monkeypatch.setattr(first, "start", lambda: None)
  events = WorkflowEvents("run_1", "agt_fixture", "scripted", [first])
  events.emit("node.started", node="shopping", attempt=1)
  events.emit("inference.completed", provider="fixture", model="scripted", duration_ms=42)
  events.emit("candidate.quarantined", exclusions={"skus": ["SUB-CARE-MO"]})
  assert first.pending_count() == 3
  with respx.mock() as mock:
    route = mock.post("http://api.test/workflow-events").respond(201)
    restarted = OutboxSink("http://api.test", "fixture", tmp_path)
    assert restarted.flush(timeout=5)
    assert restarted.stop()
  bodies = [json.loads(call.request.content) for call in route.calls]
  assert [b["phase"] for b in bodies] == ["node.started", "inference.completed", "candidate.quarantined"]
  assert all(b["type"] == "agent.step" and b["schema_version"] == 1 for b in bodies)
  assert len({b["event_id"] for b in bodies}) == 3
  assert restarted.pending_count() == 0


def test_workflow_spool_never_contains_card_details(tmp_path, monkeypatch):
  box = OutboxSink("http://api.test", "fixture", tmp_path)
  monkeypatch.setattr(box, "start", lambda: None)
  WorkflowEvents("run_1", "agt_fixture", "scripted", [box]).emit(
    "graph.failed", secret="private", card_number="4111111111111111", cvv="123")
  serialized = next(box.pending.glob("*.json")).read_text()
  assert "4111111111111111" not in serialized
  assert '"123"' not in serialized and '"private"' not in serialized
