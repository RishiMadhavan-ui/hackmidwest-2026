"""The shopper's tools and hooks inside a real Strands event loop.

FIXTURE-DRIVEN: a scripted model plays a manipulated shopper against stand-ins
for the Store MCP and Leash MCP tools. This proves the plumbing (hooks,
redaction, correlation), not that a live model falls for the injection.
"""

import json
import time

import fake_store
import pytest
from scripted_model import ScriptedModel
from strands import tool

from provenance.sink import MemorySink
from shopper.agent import build_agent
from shopper.runs import RunManager, StartRun

LISTING = fake_store.LISTING_URL
PAN = "4111111111111111"
CVV = "987"

received: dict = {}


# Stand-ins for the MCP tools, with the same names and arguments.
@tool
def list_mandates() -> str:
  """List active mandates."""
  return json.dumps({"items": [{"id": "mnd_1", "status": "active"}]})


@tool
def request_payment(
  mandate_id: str, checkout_id: str, items: list, total_cents: int, run_id: str | None = None
) -> str:
  """Request payment."""
  received["run_id"] = run_id
  return json.dumps(
    {
      "id": "pay_1",
      "status": "approved",
      "card": {"number": PAN, "exp_month": 12, "exp_year": 2028, "cvv": CVV},
    }
  )


MANIPULATED_SCRIPT = [
  [("list_mandates", {})],
  [("browse", {"url": LISTING})],
  [("create_checkout", {"sku": "SUB-CARE-MO", "quantity": 1})],
  [
    (
      "request_payment",
      {
        "mandate_id": "mnd_1",
        "checkout_id": "chk_sub",
        "items": [{"name": "USB-C charger", "quantity": 1, "unit_cents": 2999}],
        "total_cents": 2999,
      },
    )
  ],
  [
    (
      "complete_checkout",
      {
        "checkout_id": "chk_sub",
        "payment_id": "pay_1",
        "card_number": PAN,
        "exp_month": 12,
        "exp_year": 2028,
        "cvv": CVV,
      },
    )
  ],
  f"Bought the charger with card {PAN}, cvv {CVV}.",
]


TOOLS = [*fake_store.STORE_TOOLS, list_mandates, request_payment]


@pytest.fixture
def store():
  fake_store.reset()
  return fake_store.calls


def run_script(script, sink):
  received.clear()
  agent = build_agent("run_test", [sink], TOOLS, model=ScriptedModel(script))
  return agent("Buy a USB-C laptop charger for under $40. No subscriptions.")


def by_type(sink, event_type):
  return [e for e in sink.events if e["type"] == event_type]


def test_every_tool_call_traced_before_and_after(store):
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  tools = ["list_mandates", "browse", "create_checkout", "request_payment", "complete_checkout"]
  assert [e["tool_name"] for e in by_type(sink, "agent.tool.before")] == tools
  assert [e["tool_name"] for e in by_type(sink, "agent.tool.after")] == tools
  for event in sink.events:
    assert event["run_id"] == "run_test"
    assert event["event_id"].startswith("evt_")


def test_no_card_number_or_cvv_in_any_event(store):
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  dumped = json.dumps(sink.events)
  assert PAN not in dumped
  assert f'"{CVV}"' not in dumped and f"cvv {CVV}" not in dumped
  assert "****1111" in dumped


def test_run_id_injected_into_payment_request_and_page_reads(store):
  run_script(MANIPULATED_SCRIPT, MemorySink())
  assert received["run_id"] == "run_test"
  assert store["browse"][0]["run_id"] == "run_test"


def test_poisoned_source_recorded_with_hidden_instruction(store):
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  [source] = by_type(sink, "provenance.source")
  assert source["url"] == LISTING
  assert source["hidden_text_detected"] is True
  assert "SUB-CARE-MO" in source["excerpt"]
  assert source["trust_classification"] == "untrusted_web_content"
  assert source["snapshot"]["storage"] == "none"
  assert source["sha256"] == fake_store.EVIDENCE["sha256"]


def test_source_event_carries_only_contract_fields(store):
  # The shared event contract rejects unknown fields, so the Store MCP's
  # evidence_ref stays in the tool result.
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  [source] = by_type(sink, "provenance.source")
  assert "evidence_ref" not in source
  assert set(source) <= {
    "event_id", "type", "run_id", "agent_id", "agent_mode", "timestamp", "tool_use_id",
    "trust_classification", "url", "sha256", "http_status", "fetched_at",
    "hidden_text_detected", "hidden_reasons", "suspicious_phrases",
    "hidden_suspicious_phrases", "excerpt", "snapshot",
  }  # fmt: skip


def test_no_raw_html_anywhere_in_the_trace(store):
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  dumped = json.dumps(sink.events)
  assert "<div" not in dumped and "<!--" not in dumped


def test_attempted_action_and_reported_outcomes(store):
  sink = MemorySink()
  run_script(MANIPULATED_SCRIPT, sink)
  after = {e["tool_name"]: e for e in by_type(sink, "agent.tool.after")}
  assert "SUB-CARE-MO" in after["create_checkout"]["proposed_action"]
  assert after["request_payment"]["policy_decision"] == "approved"
  assert after["request_payment"]["trust_classification"] == "leash_api"
  # The store refused the charge; the trace carries the store's answer, not
  # the shopper's claim of success.
  assert after["complete_checkout"]["policy_decision"] == "error"
  assert "does not match" in after["complete_checkout"]["tool_result_summary"]


def wait_done(manager, run_id):
  for _ in range(100):
    record = manager.get(run_id)
    if record["status"] in ("completed", "failed"):
      return record
    time.sleep(0.05)
  return record


def test_run_manager_redacts_final_output(store):
  def runner(run_id, req, sinks):
    agent = build_agent(run_id, sinks, TOOLS, model=ScriptedModel(MANIPULATED_SCRIPT))
    return str(agent(req.task))

  manager = RunManager(runner=runner)
  req = StartRun(task="Buy a charger", mandate_id="mnd_1", start_url=LISTING)
  run_id = manager.start(req)["id"]
  record = wait_done(manager, run_id)
  assert record["status"] == "completed", record["error"]
  assert record["agent_mode"] == "live"
  assert PAN not in record["output"]
  assert "****1111" in record["output"]
  assert any(e["type"] == "provenance.source" for e in record["events"])
