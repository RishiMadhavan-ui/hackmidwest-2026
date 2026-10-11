"""Durable, ordered delivery of trace events to the api's intake.

Every event is redacted, written to a spool directory, and only deleted after
the api acknowledges it. A background worker delivers them in order and keeps
retrying through api outages; events left on disk when the process stops are
delivered on the next start. The api deduplicates by event_id, so a retry
after a lost acknowledgment is harmless.

Spooled files are already redacted, so no card data ever touches disk.
"""

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from provenance.redact import redact

log = logging.getLogger("leash.provenance")

# TODO: confirm the intake route with Rishi (R06). Spec 23.6 lists
# POST /provenance for sanitized agent trace claims.
INTAKE_PATH = "/provenance"

DEFAULT_SPOOL_DIR = "trace-spool"
MAX_BACKOFF_SECONDS = 30.0
# These mean the api will never accept this exact event; retrying won't help.
_PERMANENT_STATUSES = {400, 401, 403, 404, 413, 422}
# 409 means the api already stored this event_id: delivered.
_DONE_STATUSES = {409}


class OutboxSink:
  def __init__(
    self,
    api_url: str,
    token: str,
    spool_dir: str | os.PathLike | None = None,
    timeout: float = 5.0,
  ) -> None:
    self.url = api_url.rstrip("/") + INTAKE_PATH
    self.headers = {"Authorization": f"Bearer {token}"}
    self.timeout = timeout
    root = Path(spool_dir or os.environ.get("TRACE_SPOOL_DIR") or DEFAULT_SPOOL_DIR)
    self.pending = root / "pending"
    self.rejected = root / "rejected"
    self.pending.mkdir(parents=True, exist_ok=True)
    self.rejected.mkdir(parents=True, exist_ok=True)
    self._wake = threading.Event()
    self._stop = threading.Event()
    self._worker: threading.Thread | None = None
    self._lock = threading.Lock()

  # -- writing -------------------------------------------------------------

  def emit(self, event: dict[str, Any]) -> None:
    clean = redact(event)
    # Sortable names keep delivery in the order events happened, including
    # after a restart.
    name = f"{time.time_ns():020d}-{clean.get('event_id') or uuid.uuid4().hex}.json"
    tmp = self.pending / f".{name}.tmp"
    with tmp.open("w", encoding="utf-8") as stream:
      stream.write(json.dumps(clean, default=str))
      stream.flush()
      os.fsync(stream.fileno())
    os.replace(tmp, self.pending / name)
    self.start()
    self._wake.set()

  # -- delivery ------------------------------------------------------------

  def start(self) -> None:
    with self._lock:
      if self._worker is None or not self._worker.is_alive():
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="trace-outbox", daemon=True)
        self._worker.start()

  def stop(self, timeout: float | None = 5.0) -> bool:
    """Stop the worker and wait up to `timeout` seconds for it to exit.

    Never deletes anything: an event is only removed after the api has
    acknowledged it, so whatever is still pending stays spooled for the next
    worker. Returns True once the worker has exited. False means it is still
    finishing an in-flight post (bounded by the request timeout).
    """
    self._stop.set()
    self._wake.set()
    worker = self._worker
    if worker is None or worker is threading.current_thread():
      return True
    worker.join(timeout)
    return not worker.is_alive()

  def pending_count(self) -> int:
    return len(self._files())

  def flush(self, timeout: float = 10.0) -> bool:
    """Wait until everything spooled so far is delivered or rejected."""
    self.start()
    self._wake.set()
    deadline = time.monotonic() + timeout
    while self._files():
      if time.monotonic() > deadline:
        return False
      time.sleep(0.05)
    return True

  def _files(self) -> list[Path]:
    return sorted(p for p in self.pending.glob("*.json"))

  def _deliver(self, path: Path) -> str:
    """Try one event. Returns "done", "rejected", or "retry"."""
    try:
      body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
      return "rejected"
    try:
      # Workflow metadata uses a private versioned intake. Frozen R01
      # /provenance still accepts only genuine tool/source reports.
      url = self.url
      if body.get("type") == "agent.step" and body.get("schema_version") == 1:
        url = self.url.removesuffix(INTAKE_PATH) + "/workflow-events"
      res = httpx.post(url, json=body, headers=self.headers, timeout=self.timeout)
    except httpx.HTTPError as exc:
      log.warning("trace intake unreachable (%s); will retry", type(exc).__name__)
      return "retry"
    if res.is_success or res.status_code in _DONE_STATUSES:
      return "done"
    if res.status_code in _PERMANENT_STATUSES:
      log.error(
        "trace intake rejected %s %s with HTTP %s",
        body.get("type"),
        body.get("event_id"),
        res.status_code,
      )
      return "rejected"
    log.warning("trace intake returned HTTP %s; will retry", res.status_code)
    return "retry"

  def _run(self) -> None:
    backoff = 0.5
    while not self._stop.is_set():
      files = self._files()
      if not files:
        self._wake.wait(timeout=1.0)
        self._wake.clear()
        continue
      head = files[0]
      outcome = self._deliver(head)
      if outcome == "retry":
        # Hold the head of the line so the api sees events in order.
        self._stop.wait(timeout=backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        continue
      backoff = 0.5
      try:
        if outcome == "done":
          head.unlink()
        else:
          os.replace(head, self.rejected / head.name)
      except FileNotFoundError:
        pass


_shared: dict[tuple[str, str, str], OutboxSink] = {}
_shared_lock = threading.Lock()


def shared_outbox(api_url: str, token: str, lane: str) -> OutboxSink:
  """One outbox per credential, each with its own spool folder (`lane`).

  Every event must reach the api with the credential of the run that produced
  it. Separate folders keep one worker from ever delivering another
  credential's events.
  """
  root = Path(os.environ.get("TRACE_SPOOL_DIR") or DEFAULT_SPOOL_DIR)
  key = (api_url, token, str(root), lane)
  with _shared_lock:
    if key not in _shared:
      _shared[key] = OutboxSink(api_url, token, root / lane)
    return _shared[key]
