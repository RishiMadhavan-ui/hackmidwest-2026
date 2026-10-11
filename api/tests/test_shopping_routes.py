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
        run_id="run_abc",
        launch_id="launch_secret_value_at_least_32_chars",
        agent_mode="scripted",
      )
    self.assertEqual(payload["sku"], "SUB-CARE-MO")
    self.assertEqual(payload["claim_sku"], "CHG-65W")
    self.assertEqual(payload["run_id"], "run_abc")
    self.assertEqual(payload["launch_id"], "launch_secret_value_at_least_32_chars")
    self.assertEqual(payload["start_url"], "http://store:8000/products/voltcare")

  def test_live_does_not_send_scripted_sku_fields(self):
    with patch.dict("os.environ", {"STORE_URL": "http://store:8000"}):
      payload = _agents_payload(
        StartShoppingBody(mandate_id=MND, agent_mode="live"),
        task="demo task",
        run_id="run_live",
        launch_id="launch_secret_value_at_least_32_chars",
        agent_mode="live",
      )
    self.assertNotIn("sku", payload)
    self.assertEqual(payload["run_id"], "run_live")
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

  def test_launches_then_proxies_with_run_and_launch_ids(self):
    mandate = _mandate()
    conn = MagicMock()
    # Preflight agent modes, then auth_user_id for activity emit.
    conn.execute.return_value.fetchone.side_effect = [
      {"allowed_modes": ["live"]},
      {"auth_user_id": "auth-user-1"},
    ]
    response = MagicMock()
    response.status_code = 202
    response.json.return_value = {
      "run_id": "run_from_launch",
      "status": "queued",
      "agent_mode": "live",
    }
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.post.return_value = response
    launched = {
      "run_id": "run_from_launch",
      "launch_id": "launch_secret_value_at_least_32_charsxx",
      "agent_mode": "live",
      "mandate_id": mandate.id,
    }
    env = {**self.env, "AGENT_TOKEN_SHOPPER": "c" * 32}

    with (
      patch.dict("os.environ", env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch(
        "shopping_routes.require_claimable_shopper",
      ) as claimable,
      patch("shopping_routes.create_human_launch", return_value=launched) as launch,
      patch("shopping_routes.emit_activity") as emit,
      patch("shopping_routes.httpx.Client", return_value=client),
    ):
      get_conn.return_value.__enter__.return_value = conn
      get_conn.return_value.__exit__.return_value = None
      result = start_shopping(
        StartShoppingBody(mandate_id=mandate.id, agent_mode="live"),
        self.human,
      )
    claimable.assert_called_once()

    self.assertEqual(result["run_id"], "run_from_launch")
    self.assertEqual(result["label"], "Live Strands shopper")
    launch.assert_called_once()
    body = client.post.call_args.kwargs["json"]
    self.assertEqual(body["run_id"], "run_from_launch")
    self.assertEqual(body["launch_id"], launched["launch_id"])
    self.assertEqual(body["mandate_id"], mandate.id)
    self.assertNotIn("launch_id", result)
    emit.assert_called_once()

  def test_rejects_mode_mismatch_before_launch(self):
    mandate = _mandate()
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "allowed_modes": ["live"],
    }
    with (
      patch.dict("os.environ", self.env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch("shopping_routes.create_human_launch") as launch,
      patch("shopping_routes.httpx.Client") as client_cls,
    ):
      get_conn.return_value.__enter__.return_value = conn
      get_conn.return_value.__exit__.return_value = None
      with self.assertRaises(AuthorityError) as err:
        start_shopping(
          StartShoppingBody(
            mandate_id=mandate.id,
            agent_mode="scripted",
            scenario="charger",
          ),
          self.human,
        )
      self.assertEqual(err.exception.status, 409)
      launch.assert_not_called()
      client_cls.assert_not_called()

  def test_rejects_when_cluster_shopper_not_bound_to_mandate(self):
    mandate = _mandate()
    conn = MagicMock()
    # First fetchone: agent modes; second: token binding for another agent.
    conn.execute.return_value.fetchone.side_effect = [
      {"allowed_modes": ["live"]},
      {"id": "agt_other", "user_id": mandate.user_id},
    ]
    env = {**self.env, "AGENT_TOKEN_SHOPPER": "c" * 32}
    with (
      patch.dict("os.environ", env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch("shopping_routes.create_human_launch") as launch,
      patch("shopping_routes.httpx.Client") as client_cls,
    ):
      get_conn.return_value.__enter__.return_value = conn
      get_conn.return_value.__exit__.return_value = None
      with self.assertRaises(AuthorityError) as err:
        start_shopping(
          StartShoppingBody(mandate_id=mandate.id, agent_mode="live"),
          self.human,
        )
      self.assertEqual(err.exception.status, 409)
      self.assertIn("cluster agent credential", err.exception.detail)
      launch.assert_not_called()
      client_cls.assert_not_called()

  def test_rejects_inactive_mandate_before_launch(self):
    mandate = _mandate(
      status=MandateStatus.PROPOSED,
      approved_at=None,
      signature=None,
      canonical_payload_hash=None,
    )
    with (
      patch.dict("os.environ", self.env),
      patch("shopping_routes.get_conn") as get_conn,
      patch("shopping_routes.lock_user_authority"),
      patch("shopping_routes.current_mandate", return_value=mandate),
      patch("shopping_routes.utc_now", return_value=NOW),
      patch("shopping_routes.create_human_launch") as launch,
      patch("shopping_routes.httpx.Client") as client_cls,
    ):
      get_conn.return_value.__enter__.return_value = MagicMock()
      get_conn.return_value.__exit__.return_value = None
      with self.assertRaises(AuthorityError) as err:
        start_shopping(StartShoppingBody(mandate_id=mandate.id), self.human)
      self.assertEqual(err.exception.status, 409)
      launch.assert_not_called()
      client_cls.assert_not_called()


if __name__ == "__main__":
  unittest.main()
