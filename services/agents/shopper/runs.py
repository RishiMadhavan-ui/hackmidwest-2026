"""Shopper runs: start one in the background, read its trace and outcome.

Run state lives in memory for this process. The durable record is the trace
events the api ingests; this registry is a convenience for the CLI, e2e tests,
and anyone polling a run.
"""

import logging
import asyncio
import os
import threading
import uuid
from contextlib import ExitStack
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from leash_shared.llm import model_id, configured_provider
from leash_shared.models import RunId
from provenance.redact import redact, redact_text
from provenance.sink import MemorySink, Sink, api_configured, default_sinks
from service_auth import require_service_token
from shopper.credentials import credential_for, AgentCredential
from shopper.registration import register_run
from shopper.scripted import ScriptedShopper
from shopper.workflow import WorkflowStopped

log = logging.getLogger("leash.shopper")


def _now() -> str:
  return datetime.now(UTC).isoformat()


def new_run_id() -> str:
  return f"run_{uuid.uuid4().hex}"


class StartRun(BaseModel):
  model_config = {"extra":"forbid"}
  task: str = Field(min_length=1,max_length=4000)
  mandate_id: str | None = None
  start_url: str | None = None
  # "live" runs the real model. "scripted" is a labeled fixture: the shopper's
  # choices are scripted, but every tool call is real.
  agent_mode: Literal["live", "scripted"] = "live"
  # Scripted mode only: the SKU to check out and the SKU to claim to Leash.
  sku: str | None = None
  claim_sku: str | None = None
  recovery_sku: str | None = None
  # Supplied by the human launch API; a service caller cannot fabricate these
  # into authority. The execution backend must validate and consume the launch.
  run_id: RunId | None = None
  launch_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
  agent_credential: str | None = Field(default=None, min_length=32, max_length=256, repr=False, exclude=True)
  agent_id: str | None = Field(default=None, pattern=r"^agt_[A-Za-z0-9_-]+$")
  lab_execution: bool = False

  @model_validator(mode="after")
  def _scripted_needs_target(self):
    if self.agent_mode == "scripted" and not (self.sku and self.mandate_id):
      raise ValueError("scripted runs need sku and mandate_id")
    if bool(self.agent_credential) != bool(self.agent_id):
      raise ValueError("Worker identity and credential must be supplied together")
    return self


def run_credential(req: StartRun):
  if req.agent_credential:
    return AgentCredential(req.agent_mode, req.agent_id, "run-scoped", req.agent_credential)
  return credential_for(req.agent_mode)


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
  credential = run_credential(req)
  return register_run(
    run_id, req.mandate_id, req.agent_mode, credential.token, model=model, provider=provider
  )


def trace_sinks(req: StartRun) -> list[Sink]:
  """Where this run's traces go: the outbox for its own credential."""
  if not api_configured():
    return default_sinks(None, req.agent_mode)
  if req.agent_credential:
    token = os.environ.get("AGENTS_SERVICE_TOKEN", "")
    if len(token) < 32:
      raise RuntimeError("Agent evidence service credential is not configured")
    return default_sinks(token, "delegated")
  return default_sinks(credential_for(req.agent_mode).token, req.agent_mode)


def make_model_for(req: StartRun):
  if req.agent_mode == "scripted":
    return ScriptedShopper(req.sku, req.mandate_id, req.start_url, req.claim_sku)
  return None  # The runtime constructs the shared shopper model.


def mcp_urls() -> tuple[str, str]:
  """(Leash MCP url, store MCP url): two separate services.

  On LKE these are http://mcp-leash:8002/mcp and http://mcp-store:8003/mcp,
  set in k8s/agents.yaml. MCP_URL is the older name for the Leash one.
  """
  leash = os.environ.get("MCP_LEASH_URL") or os.environ.get("MCP_URL", "http://localhost:8002/mcp")
  return leash, os.environ.get("MCP_STORE_URL", "http://localhost:8003/mcp")


def run_shopper(run_id: str, req: StartRun, sinks: list[Sink]) -> str:
  """Run the real bounded Graph after a backend-verified human launch/lease."""
  if not req.launch_id or req.run_id != run_id or not api_configured():
    raise RuntimeError("human launch and execution backend are required")
  return asyncio.run(_run_graph(run_id, req, sinks))


async def _run_graph(run_id: str, req: StartRun, sinks: list[Sink]) -> str:
  from strands.tools.mcp import MCPClient
  from provenance.workflow import WorkflowEvents
  from shopper.control import ExecutionControl
  from shopper.runtime import MCPWorkflowPorts
  from shopper.workflow import PurchaseWorkflow, State

  # Leash calls carry the credential bound to this run's mode, never the other.
  credential = run_credential(req)
  store_token = os.environ.get("STORE_MCP_TOKEN")
  if not store_token:
    raise RuntimeError("STORE_MCP_TOKEN is not set")

  control = ExecutionControl(os.environ["API_URL"], credential.token, run_id)
  events = WorkflowEvents(run_id, credential.agent_id, req.agent_mode, sinks)
  stack = ExitStack()
  workflow_started = False
  startup_stage = "claim"
  try:
    claim = await control.claim(req.launch_id)
    # Both MCP services must enforce this same worker scope before tools. These
    # are correlation/fencing fields, not a substitute for their credentials.
    scoped = {"X-Leash-Run-Id": run_id, "X-Leash-Worker-Id": control.worker_id,
              "X-Leash-Generation": str(control.generation)}
    if claim.get("mcp_scope_enforced") is not True:
      raise RuntimeError("MCP execution scope enforcement is unavailable")
    tokens = claim.get("scope_tokens", {})
    if not all(isinstance(tokens.get(a), str) and len(tokens[a]) >= 32 for a in ("mcp-leash", "mcp-store")):
      raise RuntimeError("Audience-bound tool credentials are unavailable")
    events.emit("lease.claimed", worker_id=control.worker_id, generation=control.generation)
    leash_url, store_url = mcp_urls()
    # SDK context entry and tool discovery are synchronous network operations.
    # Keep them off the owning event loop so the cancellation/lease watcher
    # continues running while either server starts. Never extend a stale lease.
    startup_stage = "mcp_leash_startup"
    try:
      leash = MCPClient(url=leash_url, headers={**credential.bearer(), **scoped,
        "X-Leash-Execution-Token": tokens["mcp-leash"]}, startup_timeout=5)
      store = MCPClient(url=store_url, headers={"Authorization": f"Bearer {store_token}", **scoped,
        "X-Leash-Execution-Token": tokens["mcp-store"]}, startup_timeout=5)
      async with asyncio.timeout(20):
        await asyncio.to_thread(stack.enter_context, leash)
        startup_stage = "mcp_store_startup"
        await asyncio.to_thread(stack.enter_context, store)
        startup_stage = "mcp_store_discovery"
        store_tools = await asyncio.to_thread(store.list_tools_sync)
        startup_stage = "mcp_leash_discovery"
        leash_tools = await asyncio.to_thread(leash.list_tools_sync)
      await control.check()
      ports = MCPWorkflowPorts(run_id=run_id, mandate_id=req.mandate_id,
        agent_id=credential.agent_id, mode=req.agent_mode, start_url=req.start_url,
        control=control, leash=leash, store=store,
        tools=[*store_tools, *leash_tools],
        events=events,
        trace_sinks=sinks,
        # Lab scripts only the shopper's choices. Investigation may use the
        # configured real guardian; its hooks attribute that call separately.
        # Unconfigured/offline fixtures still report unavailable, never findings.
        allow_live_guardian=req.lab_execution,
        shopper_model=(lambda state: ScriptedShopper(
          req.recovery_sku, req.mandate_id, "/catalog", req.recovery_sku)
          if state.attempt > 1 and req.recovery_sku else make_model_for(req))
          if req.agent_mode == "scripted" else None)
      from shopper.workflow import Limits
      limits = Limits(total_seconds=120) if req.lab_execution else Limits()
      ports.budget.limits = limits
      workflow_started = True
      outcome = await PurchaseWorkflow(run_id, ports, limits=limits).run()
      return outcome.outcome
    except (Exception, asyncio.CancelledError) as exc:
      if workflow_started:
        raise
      reason = str(exc) if isinstance(exc, WorkflowStopped) else startup_stage + "_failed"
      if isinstance(exc, TimeoutError):
        reason = "mcp_startup_timeout"
      # Emit only fixed classifications; provider/transport messages may contain
      # headers or secrets. No candidate or payment exists before Graph startup.
      log.warning("run %s stopped before Graph startup (%s)", run_id, reason)
      try:
        events.emit("graph.stopped", outcome="stopped", reason=reason)
      except WorkflowStopped:
        pass  # Still persist the terminal checkpoint if evidence delivery fails.
      state = State(run_id, outcome="stopped", next_node="terminal", reasons=[reason], finished=True)
      try:
        await control.save(state)
      except Exception:
        pass  # Backend expiry remains the barrier if checkpoint delivery fails.
      control.cancel(reason)
      raise WorkflowStopped(reason, "stopped") from None
  finally:
    try:
      await asyncio.to_thread(stack.close)
    finally:
      await control.close()


Runner = Callable[[str, StartRun, list[Sink]], str]


class RunManager:
  def __init__(self, runner: Runner = run_shopper, max_workers: int = 2) -> None:
    self.runner = runner
    self.runs: dict[str, dict[str, Any]] = {}
    self._traces: dict[str, MemorySink] = {}
    self._lock = threading.Lock()
    self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shopper")

  def start(self, req: StartRun) -> dict[str, Any]:
    if self.runner is run_shopper and not (req.run_id and req.launch_id and req.mandate_id):
      raise HTTPException(status_code=409, detail="A fresh human launch with run_id and launch_id is required")
    run_id = req.run_id or new_run_id()
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
      # True only after the execution backend accepts this run's lease.
      "registered": False,
      "finished_at": None,
      "output": None,
      "error": None,
    }
    with self._lock:
      if run_id in self.runs:
        raise HTTPException(status_code=409, detail="run already submitted to this worker")
      if sum(item["status"] in {"queued","running"} for item in self.runs.values()) >= 16:
        raise HTTPException(status_code=429,detail="Worker queue is full; inspect or stop the existing launch")
      finished = [key for key,item in self.runs.items() if item["status"] not in {"queued","running"}]
      for key in finished[:-100]:
        self.runs.pop(key,None)
        self._traces.pop(key,None)
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
      if req.launch_id:
        # Human-launch API already registered the exact immutable run. Do not
        # autonomously create another registration with a static agent token.
        pass  # Mark registered only after the backend actually accepts the lease.
      elif self.runner is run_shopper:
        raise RuntimeError("a fresh backend-verified human launch is required")
      elif register(run_id, req) is not None:
        record["registered"] = True
      output = self.runner(run_id, req, sinks)
      # Keep output redacted for injected historical runners as well.
      record["output"] = redact_text(output)
      record["status"] = output if output in {
        "blocked", "authorized", "reconciling", "declined", "stopped", "cancelled", "no_candidate"
      } else "completed"
    except Exception as exc:  # a failed run is reported, not raised
      log.warning("run %s failed (%s)", run_id, type(exc).__name__)
      record["error"] = redact_text(f"{type(exc).__name__}: {exc}")
      record["status"] = exc.outcome if isinstance(exc, WorkflowStopped) and exc.outcome else "failed"
    except asyncio.CancelledError:
      record["status"] = "cancelled"
    finally:
      if req.launch_id:
        record["registered"] = any(e.get("phase") == "lease.claimed" for e in trace.events)
      record["finished_at"] = _now()

  def get(self, run_id: str) -> dict[str, Any] | None:
    with self._lock:
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
