"""Human shopping-start proxy; agents service token never leaves the API."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402

from authority_errors import AuthorityError  # noqa: E402
from leash_shared.models import MandateStatus, PurchaseMandate  # noqa: E402
from principals import Principal  # noqa: E402
from shopping_routes import StartShoppingBody, _agents_payload, start_shopping  # noqa: E402

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
SIG = base64.b64encode(bytes(64)).decode()
MND = "mnd_charger_demo"


def _mandate(**overrides) -> PurchaseMandate:
  base = {
    "id": MND,
    "user_id": "usr_" + "a" * 32,
    "agent_id": "agt_" + "b" * 32,
    "description": "Buy a USB-C laptop charger for under $40. No subscriptions.",
    "category": "laptop_charger",
    "max_cents": 3999,
    "valid_from": NOW - timedelta(minutes=1),
    "valid_until": NOW + timedelta(minutes=20),
    "created_at": NOW - timedelta(minutes=1),
    "approved_at": NOW - timedelta(seconds=30),
    "signature": SIG,
    "status": "active",
  }
  base.update(overrides)
  return PurchaseMandate.model_validate(base)


class ShoppingPayloadTests(unittest.TestCase):
  def test_scripted_attack_binds_subscription_sku_and_charger_claim(self):
    with patch.dict("os.environ", {"STORE_URL": "http://store:8000"}):
      payload = _agents_payload(
        StartShoppingBody(
          mandate_id=MND,
          agent_mode="scripted",
          scenario="subscription_attack",
        ),
        task="demo task",
      )
    self.assertEqual(payload["sku"], "SUB-CARE-MO")
    self.assertEqual(payload["claim_sku"], "CHG-65W")
    self.assertEqual(payload["start_url"], "http://store:8000/products/voltcare")

  def test_live_does_not_send_scripted_sku_fields(self):
    with patch.dict("os.environ", {"STORE_URL": "http://store:8000"}):
      payload = _agents_payload(
        StartShoppingBody(mandate_id=MND, agent_mode="live"),
        task="demo task",
      )
    self.assertNotIn("sku", payload)
    self.assertEqual(payload["start_url"], "http://store:8000/products/chg-65w")


class ShoppingStartTests(unittest.TestCase):
  def setUp(self):
    self.human = Principal("human", "usr_" + "a" * 32)
    self.env = {
      "AGENTS_URL": "http://agents.test",
      "AGENTS_SERVICE_TOKEN": "s" * 32,
      "STORE_URL": "http://store:8000",
    }

  def test_refuses_when_agents_token_missing(self):
    with patch.dict("os.environ", {"AGENTS_URL": "http://agents.test", "AGENTS_SERVICE_TOKEN": ""}, clear=False):
      with self.assertRaises(AuthorityError) as err:
        start_shopping(StartShoppingBody(mandate_id=MND), self.human)
      self.assertEqual(err.exception.status, 503)

  def test_proxies_with_service_token_and_emits_activity(self):
    mandate = _mandate()
    conn = MagicMock()
    response = MagicMock()
    response.status_code = 202
    response.json.return_value = {"run_id": "run_abc", "status": "running", "agent_mode": "live"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.post.return_value = response

    with (
      patch.dict("os.environ", self.env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch("shopping_routes.emit_activity") as emit,
      patch("shopping_routes.httpx.Client", return_value=client),
    ):
      get_conn.return_value.__enter__.return_value = conn
      get_conn.return_value.__exit__.return_value = None
      result = start_shopping(
        StartShoppingBody(mandate_id=mandate.id, agent_mode="live"),
        self.human,
      )

    self.assertEqual(result["run_id"], "run_abc")
    self.assertEqual(result["label"], "Live Strands shopper")
    headers = client.post.call_args.kwargs["headers"]
    self.assertEqual(headers["Authorization"], "Bearer " + ("s" * 32))
    body = client.post.call_args.kwargs["json"]
    self.assertEqual(body["mandate_id"], mandate.id)
    self.assertEqual(body["agent_mode"], "live")
    emit.assert_called_once()
    self.assertEqual(emit.call_args.kwargs["event_type"], "shopping.start.requested")

  def test_rejects_inactive_mandate_before_agents_call(self):
    mandate = _mandate(
      status=MandateStatus.PROPOSED,
      approved_at=None,
      signature=None,
    )
    conn = MagicMock()
    with (
      patch.dict("os.environ", self.env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch("shopping_routes.httpx.Client") as client_cls,
    ):
      get_conn.return_value.__enter__.return_value = conn
      get_conn.return_value.__exit__.return_value = None
      with self.assertRaises(AuthorityError) as err:
        start_shopping(StartShoppingBody(mandate_id=mandate.id), self.human)
      self.assertEqual(err.exception.status, 409)
      client_cls.assert_not_called()


if __name__ == "__main__":
  unittest.main()
