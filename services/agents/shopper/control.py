"""Owning-worker cancellation and a fail-closed backend execution lease client.

No local lock is advertised as Kubernetes fencing. The execution-v1 API must
atomically bind a fresh human launch to one worker before this client can run.
An old API (404 / missing capability) cannot silently start an unfenced worker.
"""

import asyncio
import threading
import time
import uuid
from contextlib import suppress
from urllib.parse import quote

import httpx

from shopper.workflow import WorkflowStopped


class ExecutionControl:
  def __init__(self, api_url, token, run_id, *, poll_seconds=0.5, client=None):
    self.client = client or httpx.AsyncClient(
      base_url=api_url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
      timeout=3.0, follow_redirects=False,
    )
    self.run_id = run_id
    self.path = "/agent-runs/" + quote(run_id, safe="")
    self.worker_id = "worker_" + uuid.uuid4().hex
    self.generation = None
    self.lease_deadline = 0.0
    self.cancel_signal = threading.Event()
    self.reason = None
    self.poll_seconds = poll_seconds
    self._agents = []
    self._lock = asyncio.Lock()
    self._watcher = None

  async def _request(self, method, suffix, **kwargs):
    try:
      response = await self.client.request(method, self.path + suffix, **kwargs)
      if response.status_code in {404, 501}:
        raise WorkflowStopped("execution_backend_unavailable")
      if not response.is_success:
        raise WorkflowStopped("execution_scope_rejected")
      body = response.json()
      if not isinstance(body, dict):
        raise ValueError()
      return body
    except (httpx.HTTPError, ValueError):
      raise WorkflowStopped("execution_control_unavailable") from None

  def _binding(self):
    return {"worker_id": self.worker_id, "generation": self.generation}

  def _validate(self, body, *, claim=False):
    generation = body.get("generation")
    valid = (
      body.get("protocol") == "execution-v1"
      and body.get("run_id") == self.run_id and body.get("worker_id") == self.worker_id
      and type(generation) is int and generation > 0
      and (claim or generation == self.generation)
      and body.get("authority_current") is True and body.get("cancel_requested") is False
      and body.get("human_launch_verified") is True
      and body.get("financial_state") in {"unspent", "reserved", "reconciling", "authorized"}
      and type(body.get("lease_seconds")) in (int, float)
      and 1 <= body["lease_seconds"] <= 30
    )
    if not valid:
      raise WorkflowStopped("execution_scope_invalid_or_stopped")
    self.generation = generation
    # Network time is subtracted by the caller; expired responses never revive.
    return body["lease_seconds"]

  async def claim(self, launch_id):
    started = time.monotonic()
    body = await self._request("POST", "/execution/claim", json={
      "protocol": "execution-v1", "worker_id": self.worker_id, "launch_id": launch_id,
    })
    self.lease_deadline = started + self._validate(body, claim=True)
    if self.lease_deadline <= time.monotonic():
      raise WorkflowStopped("execution_lease_expired")
    self._watcher = asyncio.create_task(self._watch())
    return body

  async def check(self):
    async with self._lock:
      if self.cancel_signal.is_set():
        raise WorkflowStopped(self.reason or "execution_cancelled")
      if time.monotonic() >= self.lease_deadline:
        self.cancel("execution_lease_expired")
        raise WorkflowStopped(self.reason)
      started = time.monotonic()
      try:
        body = await self._request("POST", "/execution/heartbeat", json=self._binding())
        deadline = started + self._validate(body)
        # Losing the previous lease while waiting is terminal for THIS worker.
        if time.monotonic() >= self.lease_deadline or deadline <= time.monotonic():
          raise WorkflowStopped("execution_lease_expired")
        self.lease_deadline = deadline
      except WorkflowStopped as exc:
        self.cancel(str(exc))
        raise

  async def save(self, state):
    await self._request("POST", "/execution/checkpoint", json={
      **self._binding(), "progress": state.checkpoint(),
    })

  async def _watch(self):
    try:
      while not self.cancel_signal.is_set():
        await asyncio.sleep(self.poll_seconds)
        await self.check()
    except WorkflowStopped:
      pass  # check() latched cancellation; active invocation observes the signal.

  def attach(self, agent):
    self._agents.append(agent)

  def detach(self, agent):
    self._agents.remove(agent)

  def cancel(self, reason="execution_cancelled"):
    self.reason = self.reason or reason
    self.cancel_signal.set()
    for agent in list(self._agents):
      agent.cancel()

  async def close(self):
    if self._watcher:
      self._watcher.cancel()
      with suppress(asyncio.CancelledError):
        await self._watcher
    await self.client.aclose()
