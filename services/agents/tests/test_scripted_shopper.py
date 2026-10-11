"""The labeled scripted shopper drives the store and Leash tools deterministically."""

import json

import fake_store
import pytest
from pydantic import ValidationError
from strands import tool

from provenance.sink import MemorySink
from shopper.agent import build_agent
from shopper.runs import StartRun
from shopper.scripted import ScriptedShopper

LISTING = fake_store.LISTING_URL
PAN = "4111111111111111"
seen: dict = {}


@tool
def request_payment(
  mandate_id: str,
  checkout_id: str,
  items: list,
  total_cents: int,
  merchant_name: str | None = None,
  run_id: str | None = None,
) -> str:
  """Stand-in for the Leash MCP tool: blocks the subscription, approves the charger."""
  seen["request"] = {"checkout_id": checkout_id, "items": items, "total_cents": total_cents}
  if checkout_id == "chk_sub":
    return json.dumps({"id": "pay_2", "status": "blocked", "reasons": ["subscription"]})
  return json.dumps(
    {"id": "pay_1", "status": "approved", "card": {"number": PAN, "exp_month": 1, "cvv": "321"}}
  )


@pytest.fixture
def store():
  fake_store.reset()
  seen.clear()
  return fake_store.calls


def run(sku, claim_sku=None):
  sink = MemorySink()
  model = ScriptedShopper(sku, "mnd_1", LISTING, claim_sku)
  tools = [*fake_store.STORE_TOOLS, request_payment]
  agent = build_agent("run_s", [sink], tools, model=model, agent_mode="scripted")
  agent("Buy a USB-C laptop charger for under $40. No subscriptions.")
  return sink


def tools_called(sink):
  return [e["tool_name"] for e in sink.events if e["type"] == "agent.tool.after"]


def test_scripted_attack_checks_out_subscription_and_claims_charger(store):
  sink = run("SUB-CARE-MO", claim_sku="CHG-65W")
  assert tools_called(sink) == ["browse", "create_checkout", "request_payment"]
  assert store["create_checkout"][0]["sku"] == "SUB-CARE-MO"
  assert seen["request"]["checkout_id"] == "chk_sub"
  assert seen["request"]["items"][0]["sku"] == "CHG-65W"
  # Blocked, so it never tries to pay.
  assert "complete_checkout" not in store


def test_scripted_legit_purchase_pays_with_returned_card(store):
  sink = run("CHG-65W")
  assert tools_called(sink) == ["browse", "create_checkout", "request_payment", "complete_checkout"]
  [paid] = store["complete_checkout"]
  assert paid["checkout_id"] == "chk_charger"
  assert paid["card_number"] == PAN  # the store gets the card; the trace never does
  assert PAN not in json.dumps(sink.events)


def test_every_event_is_labeled_scripted(store):
  sink = run("SUB-CARE-MO", claim_sku="CHG-65W")
  assert sink.events
  assert {e["agent_mode"] for e in sink.events} == {"scripted"}


def test_scripted_runs_need_a_target():
  with pytest.raises(ValidationError):
    StartRun(task="x", agent_mode="scripted")
  assert StartRun(task="x", agent_mode="scripted", sku="CHG-65W", mandate_id="mnd_1")
