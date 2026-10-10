"""Strands before/after tool hooks that record what the agent actually did.

Hooks are observability and correlation, not enforcement. The api, the store's
protected charge, and the rail enforce authorization on their own even if a
tool is called with no hook attached (AGENTS.md invariant 7).
"""

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from provenance.inspect import inspect_page
from provenance.redact import redact, redact_text
from provenance.sink import Sink, emit_all
from provenance.snapshots import upload_snapshot

# Where browse() leaves the raw HTML for the after-hook, keyed by toolUseId.
# The model only ever sees extracted text; provenance needs the exact bytes.
FETCHES_KEY = "leash_fetches"

SUMMARY_CHARS = 400

# How much to trust each tool's output. Nothing an agent reads or reports is
# merchant truth; only the Leash api's own responses are authenticated.
TRUST = {
  "browse": "untrusted_web_content",
  "create_checkout": "merchant_response_via_agent",
  "complete_checkout": "merchant_response_via_agent",
  "propose_mandate": "leash_api",
  "list_mandates": "leash_api",
  "request_payment": "leash_api",
  "check_status": "leash_api",
}
# Tools whose call is an attempt to move money or commit to a purchase.
ACTION_TOOLS = {"create_checkout", "request_payment", "complete_checkout"}


def _now() -> str:
  return datetime.now(UTC).isoformat()


def _event_id() -> str:
  return f"evt_{uuid.uuid4().hex}"


def _result_text(result: dict[str, Any] | None) -> str:
  if not result:
    return ""
  parts = []
  for block in result.get("content", []):
    if "text" in block:
      parts.append(block["text"])
    elif "json" in block:
      parts.append(json.dumps(block["json"], default=str))
  return "\n".join(parts)


def _result_json(text: str) -> dict[str, Any] | None:
  try:
    value = json.loads(text)
  except (ValueError, TypeError):
    return None
  return value if isinstance(value, dict) else None


def _source_reference(name: str, args: dict[str, Any]) -> str | None:
  if name == "browse":
    return args.get("url")
  if "checkout_id" in args:
    return f"checkout:{args['checkout_id']}"
  if name == "check_status":
    return f"payment:{args.get('payment_id')}"
  return None


def _proposed_action(name: str, args: dict[str, Any]) -> str | None:
  if name == "create_checkout":
    return f"start checkout for SKU {args.get('sku')} x{args.get('quantity', 1)}"
  if name == "request_payment":
    return (
      f"request payment of {args.get('total_cents')} cents for checkout "
      f"{args.get('checkout_id')} under mandate {args.get('mandate_id')}"
    )
  if name == "complete_checkout":
    return f"pay checkout {args.get('checkout_id')} with payment {args.get('payment_id')}"
  return None


class ProvenanceHooks(HookProvider):
  def __init__(
    self,
    run_id: str,
    agent_id: str,
    sinks: list[Sink],
    upload: Callable[[str, str, str], dict[str, Any]] = upload_snapshot,
    agent_mode: str = "live",
  ) -> None:
    self.run_id = run_id
    # "live" or "scripted". Rides on every event so a scripted fixture run can
    # never be shown as a live model's behavior.
    self.agent_mode = agent_mode
    self.agent_id = agent_id
    self.sinks = sinks
    self.upload = upload
    self._started: dict[str, float] = {}

  def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
    registry.add_callback(BeforeToolCallEvent, self.before_tool)
    registry.add_callback(AfterToolCallEvent, self.after_tool)

  def _base(self, event_type: str, tool_use: dict[str, Any]) -> dict[str, Any]:
    name = tool_use["name"]
    args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
    return {
      "event_id": _event_id(),
      "type": event_type,
      "run_id": self.run_id,
      "agent_id": self.agent_id,
      "agent_mode": self.agent_mode,
      "timestamp": _now(),
      "tool_name": name,
      "tool_use_id": tool_use["toolUseId"],
      "tool_arguments": redact(args),
      "source_reference": _source_reference(name, args),
      "trust_classification": TRUST.get(name, "untrusted_tool_output"),
      "proposed_action": _proposed_action(name, args),
    }

  def before_tool(self, event: BeforeToolCallEvent) -> None:
    tool_use = event.tool_use
    # Tie every payment request to this run so the api and guardian can pull
    # the pages this run read. Correlation only; it grants nothing.
    if tool_use["name"] == "request_payment" and isinstance(tool_use.get("input"), dict):
      tool_use["input"]["run_id"] = self.run_id
    self._started[tool_use["toolUseId"]] = time.monotonic()
    emit_all(self.sinks, self._base("agent.tool.before", tool_use))

  def after_tool(self, event: AfterToolCallEvent) -> None:
    tool_use = event.tool_use
    name = tool_use["name"]
    text = _result_text(event.result)
    parsed = _result_json(text)
    started = self._started.pop(tool_use["toolUseId"], None)

    record = self._base("agent.tool.after", tool_use)
    record.update(
      {
        "status": (event.result or {}).get("status", "error"),
        "error": type(event.exception).__name__ if event.exception else None,
        "tool_result_summary": redact_text(text[:SUMMARY_CHARS]),
        # The outcome Leash or the merchant reported, verbatim. An agent's own
        # narrative never fills this field.
        "policy_decision": parsed.get("status") if parsed and name in ACTION_TOOLS else None,
        "duration_ms": round((time.monotonic() - started) * 1000) if started else None,
      }
    )
    emit_all(self.sinks, record)

    if name == "browse":
      self._record_source(event, tool_use)

  def _record_source(self, event: AfterToolCallEvent, tool_use: dict[str, Any]) -> None:
    fetches = event.invocation_state.get(FETCHES_KEY, {})
    fetch = fetches.pop(tool_use["toolUseId"], None)
    if not fetch:
      return  # the fetch failed before any content arrived; the after event says why
    page = inspect_page(fetch["html"])
    snapshot = self.upload(self.run_id, page["sha256"], fetch["html"])
    emit_all(
      self.sinks,
      {
        "event_id": _event_id(),
        "type": "provenance.source",
        "run_id": self.run_id,
        "agent_id": self.agent_id,
        "agent_mode": self.agent_mode,
        "timestamp": _now(),
        "tool_use_id": tool_use["toolUseId"],
        "url": fetch["url"],
        "http_status": fetch["status_code"],
        "fetched_at": fetch["fetched_at"],
        "trust_classification": "untrusted_web_content",
        "snapshot": snapshot,
        **page,
      },
    )
