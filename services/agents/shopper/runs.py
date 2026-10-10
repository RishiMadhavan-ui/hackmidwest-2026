"""Shopper runs: start one in the background, read its trace and outcome.

Run state lives in memory for this process. The durable record is the trace
events the api ingests; this registry is a convenience for the CLI, e2e tests,
and anyone polling a run.
"""

import logging
import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from provenance.redact import redact, redact_text
from provenance.sink import MemorySink, Sink, default_sinks
from shopper.agent import build_agent, task_prompt

log = logging.getLogger("leash.shopper")


def _now() -> str:
  return datetime.now(UTC).isoformat()


def new_run_id() -> str:
  return f"run_{uuid.uuid4().hex}"


def run_shopper(run_id: str, prompt: str, sinks: list[Sink]) -> str:
  """Run the real shopper with the Leash tools loaded from the MCP server."""
  from strands.tools.mcp import MCPClient

  mcp_url = os.environ.get("MCP_URL", "http://localhost:8002/mcp")
  token = os.environ.get("AGENT_TOKEN_SHOPPER")
  if not token:
    raise RuntimeError("AGENT_TOKEN_SHOPPER is not set")

  client = MCPClient(url=mcp_url, headers={"Authorization": f"Bearer {token}"})
  with client:
    agent = build_agent(run_id, sinks, client.list_tools_sync())
    result = agent(prompt)
  return str(result)


Runner = Callable[[str, str, list[Sink]], str]


class RunManager:
  def __init__(self, runner: Runner = run_shopper, max_workers: int = 2) -> None:
    self.runner = runner
    self.runs: dict[str, dict[str, Any]] = {}
    self._traces: dict[str, MemorySink] = {}
    self._lock = threading.Lock()
    self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shopper")

  def start(self, task: str, mandate_id: str | None, start_url: str | None) -> dict[str, Any]:
    run_id = new_run_id()
    trace = MemorySink()
    record = {
      "id": run_id,
      "status": "queued",
      "task": task,
      "mandate_id": mandate_id,
      "start_url": start_url,
      "created_at": _now(),
      "finished_at": None,
      "output": None,
      "error": None,
    }
    with self._lock:
      self.runs[run_id] = record
      self._traces[run_id] = trace
    prompt = task_prompt(task, mandate_id, start_url)
    self._pool.submit(self._execute, run_id, prompt, [trace, *default_sinks()])
    return dict(record)

  def _execute(self, run_id: str, prompt: str, sinks: list[Sink]) -> None:
    record = self.runs[run_id]
    record["status"] = "running"
    try:
      output = self.runner(run_id, prompt, sinks)
      # The model has seen card details, so its final words are redacted too.
      record["output"] = redact_text(output)
      record["status"] = "completed"
    except Exception as exc:  # a failed run is reported, not raised
      log.exception("run %s failed", run_id)
      record["error"] = redact_text(f"{type(exc).__name__}: {exc}")
      record["status"] = "failed"
    finally:
      record["finished_at"] = _now()

  def get(self, run_id: str) -> dict[str, Any] | None:
    record = self.runs.get(run_id)
    if record is None:
      return None
    return redact({**record, "events": list(self._traces[run_id].events)})


class StartRun(BaseModel):
  task: str
  mandate_id: str | None = None
  start_url: str | None = None


router = APIRouter()
manager = RunManager()


@router.post("/runs", status_code=202)
def start_run(body: StartRun) -> dict[str, Any]:
  record = manager.start(body.task, body.mandate_id, body.start_url)
  return {"run_id": record["id"], "status": record["status"]}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
  record = manager.get(run_id)
  if record is None:
    raise HTTPException(status_code=404, detail="run not found")
  return record
