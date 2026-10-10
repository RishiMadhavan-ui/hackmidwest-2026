"""A scripted shopper "model" for reliable demos and e2e scenarios.

LABELED FIXTURE. It makes the shopper's choices deterministically (which SKU
to check out, what to claim it's buying) but every action still goes through
the real tools: the real store pages, the real checkout API, and the real
Leash api through MCP. Runs using it are marked agent_mode="scripted" in the
run record and every trace event, and must be presented as a simulated
compromised agent, never as a live model falling for an injection.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from strands.models.model import Model

PRODUCT_NAMES = {
  "CHG-65W": "VoltPro 65W USB-C Laptop Charger",
  "CHG-100W": "VoltPro 100W USB-C Laptop Charger",
  "SUB-CARE-MO": "VoltPro Care+ Monthly",
}


def _last_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any]:
  """The JSON body of the most recent tool result, or {} if there isn't one."""
  for message in reversed(messages):
    for block in message.get("content", []):
      result = block.get("toolResult")
      if not result:
        continue
      for part in result.get("content", []):
        if "json" in part and isinstance(part["json"], dict):
          return part["json"]
        if "text" in part:
          try:
            value = json.loads(part["text"])
          except ValueError:
            continue
          if isinstance(value, dict):
            return value
      return {}
  return {}


class ScriptedShopper(Model):
  def __init__(
    self,
    sku: str,
    mandate_id: str,
    start_url: str | None = None,
    claim_sku: str | None = None,
  ) -> None:
    self.sku = sku
    self.mandate_id = mandate_id
    self.start_url = start_url
    # What the shopper tells Leash it's buying. An attacked shopper claims the
    # charger while checking out the subscription.
    self.claim_sku = claim_sku or sku
    self.plan = (["browse"] if start_url else []) + ["create_checkout", "request_payment", "pay"]
    self.step = 0
    self.checkout: dict[str, Any] = {}
    self.payment: dict[str, Any] = {}

  def update_config(self, **model_config: Any) -> None:
    pass

  def get_config(self) -> dict[str, Any]:
    return {"model_id": "scripted-shopper", "agent_mode": "scripted", "sku": self.sku}

  async def structured_output(self, *args: Any, **kwargs: Any):
    raise NotImplementedError("the scripted shopper does not do structured output")
    yield  # pragma: no cover

  def _next_call(self, messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | str:
    last = _last_tool_result(messages)
    while self.step < len(self.plan):
      action = self.plan[self.step]
      self.step += 1
      if action == "browse":
        return "browse", {"url": self.start_url}
      if action == "create_checkout":
        return "create_checkout", {"sku": self.sku, "quantity": 1}
      if action == "request_payment":
        self.checkout = last
        if not last.get("checkout_id"):
          return f"The store didn't return a checkout: {json.dumps(last)[:300]}"
        claimed_total = last.get("total_cents")
        claim = {
          "name": PRODUCT_NAMES.get(self.claim_sku, self.claim_sku),
          "sku": self.claim_sku,
          "quantity": 1,
          "unit_cents": claimed_total if isinstance(claimed_total, int) else 0,
        }
        return "request_payment", {
          "mandate_id": self.mandate_id,
          "checkout_id": last["checkout_id"],
          "items": [claim],
          "total_cents": claim["unit_cents"],
          "merchant_name": "Volt Supply Co.",
        }
      if action == "pay":
        self.payment = last
        if last.get("status") != "approved":
          return f"Leash did not approve the payment: {json.dumps(last)[:300]}"
        args: dict[str, Any] = {
          "checkout_id": self.checkout["checkout_id"],
          "payment_id": last.get("id") or last.get("payment_id"),
        }
        card = last.get("card") or {}
        if card.get("number"):
          args.update(
            card_number=card["number"],
            exp_month=card.get("exp_month"),
            exp_year=card.get("exp_year"),
            cvv=card.get("cvv"),
          )
        return "complete_checkout", args
    return f"Finished. Last result: {json.dumps(last)[:300]}"

  async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncIterator:
    call = self._next_call(messages)
    yield {"messageStart": {"role": "assistant"}}
    if isinstance(call, str):
      yield {"contentBlockStart": {"start": {}}}
      yield {"contentBlockDelta": {"delta": {"text": call}}}
      yield {"contentBlockStop": {}}
      yield {"messageStop": {"stopReason": "end_turn"}}
      return
    name, tool_input = call
    tool_use_id = f"scripted_{self.step}"
    yield {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": tool_use_id}}}}
    yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}
