import httpx
import respx

from provenance.sink import HttpSink, MemorySink, emit_all
from provenance.snapshots import upload_snapshot

PAN = "4111111111111111"


def test_http_sink_posts_redacted_event_with_agent_bearer():
  with respx.mock() as mock:
    route = mock.post("http://api.test/provenance").respond(202)
    HttpSink("http://api.test/", "agent-token").emit({"type": "x", "note": f"card {PAN}"})
  request = route.calls.last.request
  assert request.headers["authorization"] == "Bearer agent-token"
  assert PAN not in request.content.decode()


def test_http_sink_failure_does_not_raise():
  with respx.mock() as mock:
    mock.post("http://api.test/provenance").mock(side_effect=httpx.ConnectError("down"))
    HttpSink("http://api.test", "t").emit({"type": "x"})
    mock.post("http://api.test/provenance").respond(500)
    HttpSink("http://api.test", "t").emit({"type": "x"})


def test_one_broken_sink_does_not_stop_the_others():
  class Broken:
    def emit(self, event):
      raise RuntimeError("boom")

  good = MemorySink()
  emit_all([Broken(), good], {"type": "x"})
  assert good.events == [{"type": "x"}]


def test_snapshot_reports_missing_storage_honestly():
  assert upload_snapshot("run_1", "abc", "<html>")["storage"] == "none"
