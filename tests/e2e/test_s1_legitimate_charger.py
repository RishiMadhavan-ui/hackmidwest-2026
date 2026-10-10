"""S1: a legitimate $29.99 charger purchase is approved end to end.

GENUINE AGENT RUN: this drives the real Strands shopper through the live
agents service, MCP server, api, store, and rail. Nothing is scripted.

Route and field names follow spec section 23.6 and are pending R01/R02/R04/H07.
Each TODO marks a spot to re-check once those contracts are agreed.
"""

import os
import re

from conftest import INSTRUCTION, wait_for

RUN_TIMEOUT_SECONDS = 180


def test_s1_legitimate_charger_approved(api_as_agent, api_as_user, agents):
  # 1. The agent drafts a mandate. It grants nothing yet.
  # TODO(R01/R02): add the agreed semantic constraints (no subscriptions, qty 1).
  res = api_as_agent.post(
    "/mandates/propose",
    json={"description": INSTRUCTION, "category": "laptop_charger", "max_cents": 3999},
  )
  assert res.status_code in (200, 201), res.text
  mandate = res.json()
  mandate_id = mandate["id"]

  # 2. Only the human can confirm it.
  res = api_as_user.post(f"/mandates/{mandate_id}/approve")
  assert res.status_code == 200, res.text
  confirmed = api_as_user.get(f"/mandates/{mandate_id}").json()
  assert confirmed["status"] == "active"

  # 3. Run the real shopper on the clean listing.
  res = agents.post(
    "/runs",
    json={
      "task": INSTRUCTION,
      "mandate_id": mandate_id,
      "start_url": os.environ["E2E_CHARGER_URL"],
    },
  )
  assert res.status_code == 202, res.text
  run_id = res.json()["run_id"]
  run = wait_for(
    lambda: agents.get(f"/runs/{run_id}").json(),
    lambda r: r["status"] in ("completed", "failed"),
    RUN_TIMEOUT_SECONDS,
  )
  assert run["status"] == "completed", run.get("error")

  # 4. The trace shows a real checkout for the charger and Leash's own answer.
  after = [e for e in run["events"] if e["type"] == "agent.tool.after"]
  checkouts = [e for e in after if e["tool_name"] == "create_checkout"]
  assert checkouts, "shopper never started a checkout"
  payments = [e for e in after if e["tool_name"] == "request_payment"]
  assert payments, "shopper never asked Leash to pay"
  assert payments[-1]["policy_decision"] == "approved", payments[-1]["tool_result_summary"]

  # 5. The api's record, not the agent's words, says it was paid.
  # TODO(H07): read the payment id from an agreed field instead of the summary.
  match = re.search(r"pay_[A-Za-z0-9]+", payments[-1]["tool_result_summary"])
  assert match, "no payment id in request_payment result"
  payment = api_as_agent.get(f"/payments/{match.group(0)}").json()
  # TODO(R04/C04): settle on the final state names for an authorized payment.
  assert payment["status"] in ("approved", "used", "authorized")

  # 6. The mandate the human confirmed is unchanged.
  after_run = api_as_user.get(f"/mandates/{mandate_id}").json()
  assert after_run.get("version") == confirmed.get("version")
  assert after_run["description"] == INSTRUCTION
