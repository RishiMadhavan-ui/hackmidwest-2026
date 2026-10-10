"""S1: a legitimate $29.99 charger purchase is approved end to end (session A)."""

import os

from conftest import (
  assert_mandate_unchanged,
  payment_id,
  propose_and_confirm,
  run_shopper,
  tool_results,
)


def test_s1_legitimate_charger_approved(api_as_agent, api_as_user, agents):
  mandate = propose_and_confirm(api_as_agent, api_as_user)
  run = run_shopper(agents, mandate["id"], os.environ["E2E_CHARGER_URL"], sku="CHG-65W")

  assert tool_results(run, "create_checkout"), "shopper never started a checkout"
  [payment_event] = tool_results(run, "request_payment")[-1:]
  assert payment_event["policy_decision"] == "approved", payment_event["tool_result_summary"]

  # The store's answer, not the agent's words, says the checkout was paid.
  [complete] = tool_results(run, "complete_checkout")[-1:]
  assert complete["policy_decision"] not in ("error", "declined"), complete["tool_result_summary"]

  # The api's own record agrees.
  payment = api_as_agent.get(f"/payments/{payment_id(payment_event)}").json()
  # TODO(R04/C04): settle on the final state names for an authorized payment.
  assert payment["status"] in ("approved", "used", "authorized", "paid")

  assert_mandate_unchanged(api_as_user, mandate)
