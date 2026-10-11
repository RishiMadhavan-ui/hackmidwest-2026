"""Where trace and provenance events go.

Events are redacted once more right before they leave, so a sink can never be
the place a card number slips through. Delivery to the api goes through a
durable outbox (provenance/outbox.py), so an api outage or a restart delays
traces instead of losing them, and it never stops the agent run.
"""

import json
import logging
import os
from typing import Any, Protocol

from provenance.outbox import shared_outbox
from provenance.redact import redact

log = logging.getLogger("leash.provenance")


class Sink(Protocol):
  def emit(self, event: dict[str, Any]) -> None: ...


class MemorySink:
  """Keeps events in a list. Used by the run registry and tests."""

  def __init__(self) -> None:
    self.events: list[dict[str, Any]] = []

  def emit(self, event: dict[str, Any]) -> None:
    self.events.append(redact(event))


class LogSink:
  def emit(self, event: dict[str, Any]) -> None:
    log.info("trace %s", json.dumps(redact(event), default=str))


def api_configured() -> bool:
  return bool(os.environ.get("API_URL"))


def default_sinks(token: str | None, lane: str) -> list[Sink]:
  """Trace delivery for one credential: its outbox lane, or logs if local-only."""
  if api_configured():
    if not token:
      raise RuntimeError("an agent credential is required to send traces to the api")
    return [shared_outbox(os.environ["API_URL"], token, lane)]
  return [LogSink()]


def emit_all(sinks: list[Sink], event: dict[str, Any]) -> None:
  clean = redact(event)
  for sink in sinks:
    try:
      sink.emit(clean)
    except Exception:  # one broken sink must not stop the others or the run
      log.exception("trace sink %s failed", type(sink).__name__)
