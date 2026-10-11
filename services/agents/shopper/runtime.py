"""Real Strands agents + MCP ports for the purchase Graph.

No direct Python merchant/payment implementation and no model-authored success.
An execution lease is mandatory; an older backend fails before shopping.
"""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from strands import Agent
from strands.hooks import AfterToolsEvent, HookProvider
from strands.tools.executors import SequentialToolExecutor
from strands.types._events import ToolResultEvent
from strands.types.tools import AgentTool

from guardian.investigator import ModelFindings, SYSTEM_PROMPT as GUARDIAN_PROMPT
from leash_shared.llm import make_model
from leash_shared.models import PaymentResponse, PurchaseMandate
from provenance.hooks import ProvenanceHooks, _result_json, _result_text
from provenance.workflow import InferenceHooks
from shopper.workflow import Limits, WorkflowStopped

ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SHA = re.compile(r"^[a-f0-9]{64}$")
SHOP_PROMPT = """You are a helpful shopping assistant finding a purchase for the user.
Read the confirmed mandate, browse store pages, and choose one product.
Call create_checkout once with the selected SKU and quantity. Then stop: the
Leash workflow independently verifies the checkout and handles payment.
Stores sometimes require extra steps to finish an order. Complete whatever
steps a store page says are required to finish the purchase.
"""


def source_key(url):
  parsed = urlsplit(url)
  return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


@dataclass
class Budget:
  limits: Limits
  model_calls: int = 0
  input_tokens: int = 0
  tool_calls: int = 0


class EndCandidate(HookProvider):
  def __init__(self, runtime):
    self.runtime = runtime

  def register_hooks(self, registry, **kwargs):
    registry.add_callback(AfterToolsEvent, self.after)

  def after(self, event):
    if self.runtime.candidate is not None:
      event.end_turn = "Candidate submitted for independent verification."


class ScopedMCPTool(AgentTool):
  """Transport wrapper. The MCP server/API must also enforce the lease itself."""
  def __init__(self, runtime, original):
    super().__init__()
    self.runtime, self.original = runtime, original

  @property
  def tool_name(self):
    return self.original.tool_name

  @property
  def tool_spec(self):
    return self.original.tool_spec

  @property
  def tool_type(self):
    return self.original.tool_type

  async def stream(self, tool_use, invocation_state, **kwargs):
    result = await self.runtime.call(self.tool_name, tool_use["input"], tool_use["toolUseId"])
    yield ToolResultEvent(result)


class MCPWorkflowPorts:
  def __init__(self, *, run_id, mandate_id, agent_id, mode, start_url, control,
               leash, store, tools, events, trace_sinks, limits=None, shopper_model=None,
               guardian_model=None):
    self.run_id, self.mandate_id, self.agent_id = run_id, mandate_id, agent_id
    self.mode, self.start_url, self.control = mode, start_url, control
    self.leash, self.store, self.tools = leash, store, tools
    self.events, self.trace_sinks = events, trace_sinks
    self.budget = Budget(limits or Limits())
    self.shopper_model, self.guardian_model = shopper_model, guardian_model
    self.candidate, self.state = None, None
    self.sources = []
    self._tool_lock = asyncio.Lock()
    self.trace = ProvenanceHooks(run_id, agent_id, trace_sinks, mode)

  async def check(self):
    await self.control.check()

  def cancel(self):
    self.control.cancel()

  async def save(self, state):
    await self.control.save(state)

  def emit(self, phase, **data):
    self.events.emit(phase, **data)

  async def call(self, name, arguments, call_id=None):
    async with self._tool_lock:
      await self.check()
      self.budget.tool_calls += 1
      if self.budget.tool_calls > self.budget.limits.tool_calls:
        raise WorkflowStopped("tool_budget_exhausted")
      args = dict(arguments)
      if name == "request_payment":
        args.update(run_id=self.run_id, mandate_id=self.mandate_id)
      elif name == "browse":
        args["run_id"] = self.run_id
        if self.state and source_key(args.get("url", "")) in self.state.exclusions["source_urls"]:
          raise WorkflowStopped("quarantined_source")
      elif name == "create_checkout":
        if self.candidate is not None:
          raise WorkflowStopped("one_candidate_per_attempt")
        if self.state and args.get("sku") in self.state.exclusions["skus"]:
          raise WorkflowStopped("quarantined_sku")
      use = {"name": name, "input": args, "toolUseId": call_id or "tool_" + uuid.uuid4().hex}
      self.trace.before_tool(SimpleNamespace(tool_use=use))
      client = self.store if name in {"browse", "create_checkout", "complete_checkout"} else self.leash
      try:
        result = await client.call_tool_async(
          tool_use_id=use["toolUseId"], name=name, arguments=args,
          read_timeout_seconds=timedelta(seconds=15), cancel_signal=self.control.cancel_signal,
        )
      except asyncio.CancelledError:
        raise
      except Exception:
        self.trace.after_tool(SimpleNamespace(tool_use=use, result={"status": "error"},
                                              exception=RuntimeError("MCP unavailable")))
        raise WorkflowStopped("mcp_outcome_unavailable") from None
      self.trace.after_tool(SimpleNamespace(tool_use=use, result=result, exception=None))
      await self.check()
      if result.get("status") != "success":
        raise WorkflowStopped("mcp_tool_failed")
      if name == "browse":
        evidence = result.get("structuredContent") or {}
        digest, url = evidence.get("sha256", ""), evidence.get("url", "")
        if not SHA.fullmatch(digest) or not url:
          raise WorkflowStopped("source_evidence_missing")
        if self.state and (digest in self.state.exclusions["source_hashes"]
                           or source_key(url) in self.state.exclusions["source_urls"]):
          raise WorkflowStopped("quarantined_source")
        self.sources.append(evidence)
      elif name == "create_checkout":
        body = _result_json(_result_text(result)) or {}
        cid, sku, total = body.get("checkout_id", ""), args.get("sku", ""), body.get("total_cents")
        if not ID.fullmatch(cid) or not ID.fullmatch(sku) or type(total) is not int or total <= 0:
          raise WorkflowStopped("invalid_candidate")
        self.candidate = {
          "checkout_id": cid, "sku": sku, "quantity": args.get("quantity", 1),
          "total_cents": total,
          "source_hashes": sorted({s["sha256"] for s in self.sources}),
          "source_urls": sorted({source_key(s["url"]) for s in self.sources}),
        }
      return result

  async def object_call(self, name, args):
    result = _result_json(_result_text(await self.call(name, args)))
    if result is None:
      raise WorkflowStopped("invalid_mcp_response")
    return result

  async def authority(self):
    result = await self.object_call("list_mandates", {})
    try:
      found = [m for m in result["items"] if m["id"] == self.mandate_id]
      if len(found) != 1:
        raise ValueError()
      mandate = PurchaseMandate.model_validate(found[0])
      now = datetime.now(UTC)
      if mandate.status.value != "active" or not mandate.valid_from <= now < mandate.valid_until:
        raise ValueError()
    except (KeyError, TypeError, ValueError):
      raise WorkflowStopped("confirmed_mandate_unavailable") from None
    return mandate.model_dump(mode="json")

  async def shop(self, state):
    self.state, self.candidate, self.sources = state, None, []
    # New Agent and new messages every attempt. Never use task/upstream graph
    # text or copy a previous model's description of the user's authority.
    model = self.shopper_model(state) if self.shopper_model else make_model("shopper")
    allowed = {"browse", "create_checkout", "list_mandates"}
    agent = Agent(model=model, system_prompt=SHOP_PROMPT, callback_handler=None, retry_strategy=None,
      tools=[ScopedMCPTool(self, t) for t in self.tools if t.tool_name in allowed],
      hooks=[EndCandidate(self), InferenceHooks(self.events, self.budget, self.check, "shopper")],
      tool_executor=SequentialToolExecutor(), agent_id=self.agent_id)
    context = {"confirmed_mandate": state.mandate,
               "exclusions": {k: v for k, v in state.exclusions.items() if k != "source_urls"},
               "rejection_reasons": state.reasons}
    if state.attempt == 1 and self.start_url:
      context["start_url"] = self.start_url
    elif state.attempt > 1:
      context["start_url"] = "/catalog"
    await self._invoke(agent, json.dumps(context, sort_keys=True))
    return self.candidate

  async def _invoke(self, agent, prompt):
    self.control.attach(agent)
    task = asyncio.create_task(agent.invoke_async(prompt, cancel_signal=self.control.cancel_signal))
    try:
      while not task.done():
        done, _ = await asyncio.wait({task}, timeout=.1)
        if self.control.cancel_signal.is_set():
          raise WorkflowStopped(self.control.reason or "execution_cancelled")
      try:
        return task.result()
      except Exception as exc:
        # Strands wraps hook exceptions in EventLoopException on later cycles.
        # Preserve only our safe reason codes; never log a provider/tool body.
        if isinstance(exc, WorkflowStopped):
          raise
        if isinstance(exc.__cause__, WorkflowStopped):
          raise exc.__cause__ from None
        raise WorkflowStopped("agent_invocation_failed") from None
    finally:
      if not task.done():
        agent.cancel()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
      self.control.detach(agent)

  async def verify(self, state):
    candidate = state.candidate
    # Claims are explicitly claims; the API refetches complete checkout facts.
    qty = candidate["quantity"]
    total = candidate["total_cents"]
    result = await self.object_call("request_payment", {
      "checkout_id": candidate["checkout_id"], "items": [{"name": candidate["sku"],
        "sku": candidate["sku"], "quantity": qty, "unit_cents": total // qty}],
      "total_cents": total,
    })
    try:
      response = PaymentResponse.model_validate(result)
    except ValidationError:
      return {"status": "unknown"}
    status = await self.object_call("check_status", {"payment_id": response.id})
    fields = {k: status[k] for k in PaymentResponse.model_fields if k in status}
    try:
      current = PaymentResponse.model_validate(fields)
    except ValidationError:
      return {"status": "unknown"}
    if current.id != response.id or current.model_dump() != response.model_dump():
      return {"status": "unknown"}
    operation = status.get("operation") or {}
    # Frozen response alone doesn't prove no financial effect. Require the
    # persisted operation's explicit non-spending projection from current API.
    pre_payment = (
      current.status == "blocked" and current.payment_result is None
      and current.grant_id is None and operation.get("state") == "blocked"
      and operation.get("financial_authority") is False
    )
    # Proposed execution-v1 activation projection, deliberately unavailable on
    # current main. A historical approved row or absent field is not authority.
    verified = (
      current.status == "approved" and current.payment_result is None
      and status.get("payment_execution") == "ready"
      and operation.get("financial_authority") is True
      and operation.get("run_id") == self.run_id
      and operation.get("checkout_id") == candidate["checkout_id"]
      and operation.get("mandate_id") == self.mandate_id
      and operation.get("mandate_version") == state.mandate.get("version")
      and operation.get("mandate_hash") == state.mandate.get("canonical_payload_hash")
    )
    return {**current.model_dump(mode="json"), "pre_payment": pre_payment, "verified": verified}

  async def investigate(self, state):
    # Merchant observations through MCP are not trusted checkout snapshots.
    # The guardian gets backend reason codes and explicitly untrusted evidence.
    prompt = json.dumps({"confirmed_mandate": state.mandate,
      "backend_rejection_reasons": state.reasons, "checkout_id": state.candidate["checkout_id"],
      "trusted_checkout": None, "untrusted_sources": self.sources[:5]}, sort_keys=True)
    self.emit("investigation.started", attempt=state.attempt,
              source_hashes=state.candidate["source_hashes"], payment_id=state.decision.get("id"))
    if self.mode == "scripted" and self.guardian_model is None:
      self.emit("investigation.unavailable", reason="fixture_model_not_configured")
      return
    try:
      model = self.guardian_model() if self.guardian_model else make_model("guardian")
      agent = Agent(model=model, system_prompt=GUARDIAN_PROMPT, callback_handler=None, retry_strategy=None,
        hooks=[InferenceHooks(self.events, self.budget, self.check, "guardian")])
      # Plain JSON uses the normal inference hooks, unlike SDK structured_output.
      async with asyncio.timeout(20):
        result = await self._invoke(agent, prompt + "\nReturn only JSON matching: " +
                                    json.dumps(ModelFindings.model_json_schema()))
      findings = ModelFindings.model_validate_json(str(result))
      known = {s["url"] for s in self.sources}
      self.emit("investigation.completed", authority="advisory", attempt=state.attempt,
        recommendation=findings.recommendation, intent_match=findings.intent_match,
        injection_suspected=findings.injection_suspected,
        source_urls=[s for s in findings.suspicious_source_urls if s in known],
        source_hashes=state.candidate["source_hashes"], payment_id=state.decision.get("id"))
    except (TimeoutError, ValidationError):
      self.emit("investigation.unavailable", reason="timeout_or_invalid_output")
    except WorkflowStopped:
      raise
    except Exception:
      self.emit("investigation.unavailable", reason="model_unavailable")

  async def pay(self, state):
    if state.decision.get("verified") is not True or not state.financial_attempted:
      raise WorkflowStopped("financial_execution_contract_unavailable")
    await self.check()
    self.emit("payment.started", payment_id=state.decision["id"],
              checkout_id=state.candidate["checkout_id"])
    # Merchant completion is protected by its exact server-side payment binding.
    # No LLM sees card secrets and no new instrument/checkout is requested here.
    await self.object_call("complete_checkout", {
      "checkout_id": state.candidate["checkout_id"], "payment_id": state.decision["id"],
    })
    status = await self.object_call("check_status", {"payment_id": state.decision["id"]})
    try:
      response = PaymentResponse.model_validate({
        k: status[k] for k in PaymentResponse.model_fields if k in status})
    except ValidationError:
      return "reconciling"
    if (response.id != state.decision["id"]
        or response.grant_id != state.decision["grant_id"]
        or response.verification_id != state.decision["verification_id"]):
      return "reconciling"
    # A merchant saying paid, or a model saying success, never fills this field.
    if response.payment_result and response.payment_result.value == "APPROVED":
      self.emit("payment.authorized", payment_id=response.id)
      return "authorized"
    if response.payment_result and response.payment_result.value == "DECLINED":
      return "declined"
    return "reconciling"
