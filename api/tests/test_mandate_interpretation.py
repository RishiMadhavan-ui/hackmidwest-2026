"""Instruction parsing preserves explicit constraints; never activates authority."""

import asyncio
import unittest
from unittest.mock import patch

from authority_errors import AuthorityError
from mandate_interpretation import interpret


class InterpretationTests(unittest.TestCase):
  def test_under_forty_generates_exact_budget_and_no_subscriptions(self):
    text="Buy me a computer charger under $40. No subscriptions."
    result=asyncio.run(interpret(text))
    self.assertEqual(result["proposal"]["description"],text)
    self.assertEqual(result["proposal"]["max_cents"],3999)
    self.assertFalse(result["proposal"]["allow_subscription"])
    self.assertFalse(result["proposal"]["allow_recurring"])
    self.assertTrue(result["requires_confirmation"])
    self.assertTrue(any("connector" in item.lower() for item in result["assumptions"]))

  def test_inclusive_budget_and_wattage_constraint(self):
    result=asyncio.run(interpret("Buy one USB-C laptop charger at least 65 watts for up to $40. No subscriptions."))
    self.assertEqual(result["proposal"]["max_cents"],4000)
    self.assertIn({"name":"wattage","operator":"minimum","value":65},result["proposal"]["product_constraints"])

  def test_missing_ambiguous_or_unsupported_currency_budget_needs_clarification(self):
    for text in ["Buy a charger", "Buy a charger under $40 or under $50", "Buy a charger under $40 EUR"]:
      with self.subTest(text=text), self.assertRaises(AuthorityError) as error:
        asyncio.run(interpret(text))
      self.assertEqual(error.exception.status,422)

  def test_unrepresented_shipping_brand_and_quantity_cannot_be_silently_dropped(self):
    with patch.dict("os.environ", {"OPENAI_BASE_URL":"","INFERENCE_BASE_URL":""}):
      for text in ["Buy two chargers under $40", "Buy an Apple charger under $40", "Buy a charger under $40 delivered tomorrow"]:
        with self.subTest(text=text), self.assertRaises(AuthorityError) as error:
          asyncio.run(interpret(text))
        self.assertEqual(error.exception.status,422)
