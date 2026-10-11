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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from leash_shared.llm import model_id, configured_provider
from provenance.redact import redact, redact_text
from provenance.sink import MemorySink, Sink, api_configured, default_sinks
from service_auth import require_service_token
from shopper.agent import build_agent, task_prompt
from shopper.credentials import credential_for
from shopper.registration import register_run
from shopper.scripted import ScriptedShopper

log = logging.getLogger("leash.shopper")


def _now() -> str:
  return datetime.now(UTC).isoformat()


def new_run_id() -> str:
  return f"run_{uuid.uuid4().hex}"


class StartRun(BaseModel):
  task: str
  mandate_id: str | None = None
  start_url: str | None = None
  # "live" runs the real model. "scripted" is a labeled fixture: the shopper's
  # choices are scripted, but every tool call is real.
  agent_mode: Literal["live", "scripted"] = "live"
  # Scripted mode only: the SKU to check out and the SKU to claim to Leash.
  sku: str | None = None
  claim_sku: str | None = None

  @model_validator(mode="after")
  def _scripted_needs_target(self):
    if self.agent_mode == "scripted" and not (self.sku and self.mandate_id):
      raise ValueError("scripted runs need sku and mandate_id")
    return self


def model_identity(req: StartRun) -> tuple[str, str]:
  """What drives this run, for registration and labels: (model, provider)."""
  if req.agent_mode == "scripted":
    return "scripted-shopper", "fixture"
  return model_id(), configured_provider()


def register(run_id: str, req: StartRun) -> dict[str, Any] | None:
  """Register with the api before any trace goes out. None in local-only mode."""
  if not api_configured():
    return None
  model, provider = model_identity(req)
  credential = credential_for(req.agent_mode)
  return register_run(
    run_id, req.mandate_id, req.agent_mode, credential.token, model=model, provider=provider
  )


def trace_sinks(req: StartRun) -> list[Sink]:
  """Where this run's traces go: the outbox for its own credential."""
  if not api_configured():
    return default_sinks(None, req.agent_mode)
  return default_sinks(credential_for(req.agent_mode).token, req.agent_mode)


def make_model_for(req: StartRun):
  if req.agent_mode == "scripted":
    return ScriptedShopper(req.sku, req.mandate_id, req.start_url, req.claim_sku)
  return None  # build_agent falls back to make_model("shopper")


def mcp_urls() -> tuple[str, str]:
  """(Leash MCP url, store MCP url): two separate services.

  On LKE these are http://mcp-leash:8002/mcp and http://mcp-store:8003/mcp,
  set in k8s/agents.yaml. MCP_URL is the older name for the Leash one.
  """
  leash = os.environ.get("MCP_LEASH_URL") or os.environ.get("MCP_URL", "http://localhost:8002/mcp")
  return leash, os.environ.get("MCP_STORE_URL", "http://localhost:8003/mcp")


def run_shopper(run_id: str, req: StartRun, sinks: list[Sink]) -> str:
  """Run the shopper with tools from both MCP servers: the store and Leash.

  Each server gets its own credential. The Leash token goes only to Leash's
  server, and the store token only to the store's.
  """
  from strands.tools.mcp import MCPClient

  # Leash calls carry the credential bound to this run's mode, never the other.
  credential = credential_for(req.agent_mode)
  store_token = os.environ.get("STORE_MCP_TOKEN")
  if not store_token:
    raise RuntimeError("STORE_MCP_TOKEN is not set")

  leash_url, store_url = mcp_urls()
  leash = MCPClient(url=leash_url, headers=credential.bearer())
  store = MCPClient(url=store_url, headers={"Authorization": f"Bearer {store_token}"})
  with leash, store:
    agent = build_agent(
      run_id,
      sinks,
      [*store.list_tools_sync(), *leash.list_tools_sync()],
      model=make_model_for(req),
      agent_mode=req.agent_mode,
      agent_id=credential.agent_id,
    )
    result = agent(task_prompt(req.task, req.mandate_id, req.start_url))
  return str(result)


Runner = Callable[[str, StartRun, list[Sink]], str]


class RunManager:
  def __init__(self, runner: Runner = run_shopper, max_workers: int = 2) -> None:
    self.runner = runner
    self.runs: dict[str, dict[str, Any]] = {}
    self._traces: dict[str, MemorySink] = {}
    self._lock = threading.Lock()
    self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shopper")

  def start(self, req: StartRun) -> dict[str, Any]:
    run_id = new_run_id()
    trace = MemorySink()
    record = {
      "id": run_id,
      "status": "queued",
      "task": req.task,
      "mandate_id": req.mandate_id,
      "start_url": req.start_url,
      "agent_mode": req.agent_mode,
      "agent_label": (
        "Simulated compromised agent (scripted fixture)"
        if req.agent_mode == "scripted"
        else "Live Strands shopper"
      ),
      "created_at": _now(),
      # True once the api has bound this run to its user and mandate. False
      # means local-only mode (no API_URL): traces go to logs, nowhere else.
      "registered": False,
      "finished_at": None,
      "output": None,
      "error": None,
    }
    with self._lock:
      self.runs[run_id] = record
      self._traces[run_id] = trace
    self._pool.submit(self._execute, run_id, req, trace)
    return dict(record)

  def _execute(self, run_id: str, req: StartRun, trace: MemorySink) -> None:
    record = self.runs[run_id]
    record["status"] = "running"
    try:
      # Resolving sinks needs this mode's credential; a missing one fails the
      # run with a clear error instead of borrowing another mode's.
      sinks = [trace, *trace_sinks(req)]
      if register(run_id, req) is not None:
        record["registered"] = True
      output = self.runner(run_id, req, sinks)
      # The model has seen card details, so its final words are redacted too.
      record["output"] = redact_text(output)
      record["status"] = "completed"
    except Exception as exc:  # a failed run is reported, not raised
      log.warning("run %s failed (%s)", run_id, type(exc).__name__)
      record["error"] = redact_text(f"{type(exc).__name__}: {exc}")
      record["status"] = "failed"
    finally:
      record["finished_at"] = _now()

  def get(self, run_id: str) -> dict[str, Any] | None:
    record = self.runs.get(run_id)
    if record is None:
      return None
    return redact({**record, "events": list(self._traces[run_id].events)})


router = APIRouter(dependencies=[Depends(require_service_token)])
manager = RunManager()


@router.post("/runs", status_code=202)
def start_run(body: StartRun) -> dict[str, Any]:
  record = manager.start(body)
  return {"run_id": record["id"], "status": record["status"], "agent_mode": body.agent_mode}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
  record = manager.get(run_id)
  if record is None:
    raise HTTPException(status_code=404, detail="run not found")
  return record
