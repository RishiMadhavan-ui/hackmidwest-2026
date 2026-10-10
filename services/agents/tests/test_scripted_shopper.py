"""The labeled scripted shopper drives real tools deterministically."""

import json
from pathlib import Path

import pytest
import respx
from pydantic import ValidationError
from strands import tool

from provenance.sink import MemorySink
from shopper.agent import build_agent
from shopper.runs import StartRun
from shopper.scripted import ScriptedShopper

STORE = "http://store.test"
LISTING = f"{STORE}/products/chg-65w"
POISONED = (Path(__file__).parent / "fixtures/listings/charger_poisoned.html").read_text()
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
  """Stand-in for the MCP tool: blocks the subscription checkout, approves the charger."""
  seen["request"] = {"checkout_id": checkout_id, "items": items, "total_cents": total_cents}
  if checkout_id == "chk_sub":
    return json.dumps({"id": "pay_2", "status": "blocked", "reasons": ["subscription"]})
  return json.dumps(
    {"id": "pay_1", "status": "approved", "card": {"number": PAN, "exp_month": 1, "cvv": "321"}}
  )


@pytest.fixture
def store(monkeypatch):
  monkeypatch.setenv("STORE_URL", STORE)
  with respx.mock(assert_all_called=False) as mock:
    mock.get(LISTING).respond(200, text=POISONED)

    def checkout(request):
      sku = json.loads(request.content)["sku"]
      cid = "chk_sub" if sku == "SUB-CARE-MO" else "chk_charger"
      return respx.MockResponse(201, json={"checkout_id": cid, "total_cents": 2999})

    mock.post(f"{STORE}/api/checkouts").mock(side_effect=checkout)
    seen["complete"] = mock.post(f"{STORE}/api/checkouts/chk_charger/complete").respond(
      200, json={"status": "paid", "checkout_id": "chk_charger"}
    )
    yield mock


def run(sku, claim_sku=None):
  seen.pop("request", None)
  sink = MemorySink()
  model = ScriptedShopper(sku, "mnd_1", LISTING, claim_sku)
  agent = build_agent("run_s", [sink], [request_payment], model=model, agent_mode="scripted")
  agent("Buy a USB-C laptop charger for under $40. No subscriptions.")
  return sink


def tools_called(sink):
  return [e["tool_name"] for e in sink.events if e["type"] == "agent.tool.after"]


def test_scripted_attack_checks_out_subscription_and_claims_charger(store):
  sink = run("SUB-CARE-MO", claim_sku="CHG-65W")
  assert tools_called(sink) == ["browse", "create_checkout", "request_payment"]
  assert seen["request"]["checkout_id"] == "chk_sub"
  assert seen["request"]["items"][0]["sku"] == "CHG-65W"
  # Blocked, so it never tries to pay.
  assert not seen["complete"].called


def test_scripted_legit_purchase_pays_with_returned_card(store):
  sink = run("CHG-65W")
  assert tools_called(sink) == ["browse", "create_checkout", "request_payment", "complete_checkout"]
  body = json.loads(seen["complete"].calls.last.request.content)
  assert body["payment_id"] == "pay_1"
  assert body["card"]["number"] == PAN  # the real store gets the card; the trace never does
  assert PAN not in json.dumps(sink.events)


def test_every_event_is_labeled_scripted(store):
  sink = run("SUB-CARE-MO", claim_sku="CHG-65W")
  assert sink.events
  assert {e["agent_mode"] for e in sink.events} == {"scripted"}


def test_scripted_runs_need_a_target():
  with pytest.raises(ValidationError):
    StartRun(task="x", agent_mode="scripted")
  assert StartRun(task="x", agent_mode="scripted", sku="CHG-65W", mandate_id="mnd_1")
