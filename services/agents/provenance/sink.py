"""Where trace and provenance events go.

Events are redacted once more right before they leave, so a sink can never be
the place a card number slips through. Sending is best effort: a failed post
is logged and the agent run keeps going.
"""

import json
import logging
import os
from typing import Any, Protocol

import httpx

from provenance.redact import redact

log = logging.getLogger("leash.provenance")

# TODO: confirm the intake route with Rishi (R06). Spec 23.6 lists
# POST /provenance for sanitized agent trace claims.
INTAKE_PATH = "/provenance"


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


class HttpSink:
  """Posts each event to the api with the agent's own bearer token."""

  def __init__(self, api_url: str, token: str, timeout: float = 3.0) -> None:
    self.url = api_url.rstrip("/") + INTAKE_PATH
    self.headers = {"Authorization": f"Bearer {token}"}
    self.timeout = timeout

  def emit(self, event: dict[str, Any]) -> None:
    try:
      res = httpx.post(self.url, json=redact(event), headers=self.headers, timeout=self.timeout)
      if res.is_error:
        log.warning("provenance intake returned HTTP %s for %s", res.status_code, event.get("type"))
    except httpx.HTTPError as exc:
      # Never let observability failures crash the agent run.
      log.warning(
        "provenance intake unreachable (%s) for %s", type(exc).__name__, event.get("type")
      )


def default_sinks() -> list[Sink]:
  api_url = os.environ.get("API_URL")
  token = os.environ.get("AGENT_TOKEN_SHOPPER")
  if api_url and token:
    return [HttpSink(api_url, token)]
  return [LogSink()]


def emit_all(sinks: list[Sink], event: dict[str, Any]) -> None:
  clean = redact(event)
  for sink in sinks:
    try:
      sink.emit(clean)
    except Exception:  # one broken sink must not stop the others or the run
      log.exception("trace sink %s failed", type(sink).__name__)
