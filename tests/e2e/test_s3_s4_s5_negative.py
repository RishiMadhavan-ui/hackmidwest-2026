"""S3 over budget, S4 missing checkout evidence, S5 replay. Preflight sessions only.

S4 and S5 call the api and store directly with the agent's token instead of
going through the shopper: they prove the backend enforces the rules even
when a caller skips the agent and its hooks.
"""

import os

from conftest import (
  INSTRUCTION,
  NOT_APPROVED,
  payment_id,
  propose_and_confirm,
  run_shopper,
  tool_results,
)


def test_s3_over_budget_charger_blocked(api_as_agent, api_as_user, agents):
  mandate = propose_and_confirm(api_as_agent, api_as_user)
  run = run_shopper(agents, mandate["id"], os.environ["E2E_CHARGER_URL"], sku="CHG-100W")
  [payment_event] = tool_results(run, "request_payment")[-1:]
  assert payment_event["policy_decision"] in NOT_APPROVED, payment_event["tool_result_summary"]
  assert not tool_results(run, "complete_checkout")


def test_s4_unknown_checkout_never_approves(api_as_agent, api_as_user):
  mandate = propose_and_confirm(api_as_agent, api_as_user)
  # Direct api call: a checkout id the merchant never issued, with a glowing
  # agent description. The agent's word is not evidence.
  # TODO(H07): match the agreed POST /payments body.
  res = api_as_agent.post(
    "/payments",
    json={
      "mandate_id": mandate["id"],
      "checkout_id": "chk_does_not_exist",
      "proposal": {
        "merchant_name": "Volt Supply Co.",
        "items": [{"name": INSTRUCTION, "sku": "CHG-65W", "quantity": 1, "unit_cents": 2999}],
        "total_cents": 2999,
      },
    },
  )
  assert res.status_code < 500, res.text
  body = res.json()
  assert body.get("status") in NOT_APPROVED | {None}, body
  assert not body.get("card")


def test_s5_replayed_grant_declined(api_as_agent, api_as_user, agents, store):
  mandate = propose_and_confirm(api_as_agent, api_as_user)
  run = run_shopper(agents, mandate["id"], os.environ["E2E_CHARGER_URL"], sku="CHG-65W")
  [payment_event] = tool_results(run, "request_payment")[-1:]
  assert payment_event["policy_decision"] == "approved"
  [complete] = tool_results(run, "complete_checkout")[-1:]
  checkout_ref = complete["source_reference"]  # "checkout:<id>"
  checkout_id = checkout_ref.split(":", 1)[1]

  # Replay the same completion directly at the store. The grant is consumed.
  # TODO(H05): match the store's protected charge route.
  res = store.post(
    f"/api/checkouts/{checkout_id}/complete",
    json={"payment_id": payment_id(payment_event)},
  )
  assert res.status_code >= 400 or res.json().get("status") not in ("paid", "approved"), res.text

  # The mandate allowed one purchase. A second request under it is not approved.
  res = api_as_agent.post(
    "/payments",
    json={
      "mandate_id": mandate["id"],
      "checkout_id": checkout_id,
      "proposal": {
        "items": [
          {"name": "VoltPro 65W charger", "sku": "CHG-65W", "quantity": 1, "unit_cents": 2999}
        ],
        "total_cents": 2999,
      },
    },
  )
  # A well-formed request that's refused, not a validation error.
  assert res.status_code < 500 and res.status_code != 422, res.text
  assert res.json().get("status") in NOT_APPROVED | {None}, res.text
  assert not res.json().get("card")
