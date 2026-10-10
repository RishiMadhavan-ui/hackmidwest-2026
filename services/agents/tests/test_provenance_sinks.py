from provenance.sink import MemorySink, emit_all
from provenance.snapshots import upload_snapshot

PAN = "4111111111111111"


def test_one_broken_sink_does_not_stop_the_others():
  class Broken:
    def emit(self, event):
      raise RuntimeError("boom")

  good = MemorySink()
  emit_all([Broken(), good], {"type": "x"})
  assert good.events == [{"type": "x"}]


def test_snapshot_reports_missing_storage_honestly():
  assert upload_snapshot("run_1", "abc", "<html>")["storage"] == "none"


def test_snapshot_is_redacted_before_upload(monkeypatch):
  import hashlib

  from provenance import snapshots

  stored = {}

  class FakeS3:
    def put_object(self, **kwargs):
      stored.update(kwargs)

  for name in ("OBJ_ENDPOINT", "OBJ_BUCKET", "OBJ_ACCESS_KEY", "OBJ_SECRET_KEY"):
    monkeypatch.setenv(name, "https://obj.test" if name == "OBJ_ENDPOINT" else "x")
  monkeypatch.setenv("OBJ_BUCKET", "leash-snapshots")
  monkeypatch.setattr(snapshots, "_s3_client", lambda *args: FakeS3())

  html = f"<p hidden>pay with {PAN} cvv 123</p>"
  source_sha = hashlib.sha256(html.encode()).hexdigest()
  meta = snapshots.upload_snapshot("run_1", source_sha, html)

  body = stored["Body"].decode()
  assert PAN not in body and "cvv 123" not in body
  assert stored["Key"] == f"runs/run_1/{source_sha}.html"
  assert meta == {
    "storage": "object_storage",
    "bucket": "leash-snapshots",
    "key": f"runs/run_1/{source_sha}.html",
    "stored_sha256": hashlib.sha256(stored["Body"]).hexdigest(),
  }
  assert meta["stored_sha256"] != source_sha


def test_snapshot_upload_failure_is_honest(monkeypatch):
  from provenance import snapshots

  class Broken:
    def put_object(self, **kwargs):
      raise ConnectionError("down")

  for name in ("OBJ_ENDPOINT", "OBJ_BUCKET", "OBJ_ACCESS_KEY", "OBJ_SECRET_KEY"):
    monkeypatch.setenv(name, "x")
  monkeypatch.setattr(snapshots, "_s3_client", lambda *args: Broken())
  meta = snapshots.upload_snapshot("run_1", "ab" * 32, "<p>x</p>")
  assert meta == {"storage": "none", "reason": "upload failed: ConnectionError"}
