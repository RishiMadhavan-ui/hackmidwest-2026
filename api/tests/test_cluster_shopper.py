"""Legacy cluster credentials preserve ownership; normal UI uses private workers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402

from authority_errors import AuthorityError  # noqa: E402
from principals import ensure_cluster_shopper  # noqa: E402

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
TOKEN = "c" * 32


class EnsureClusterShopperTests(unittest.TestCase):
  def test_returns_existing_binding_for_same_human(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id": "agt_shopper",
      "user_id": USER_A,
      "enabled": True,
      "allowed_modes": ["live"],
    }
    with patch.dict("os.environ", {"AGENT_TOKEN_SHOPPER": TOKEN}, clear=False):
      agent_id = ensure_cluster_shopper(conn, USER_A, "live")
    self.assertEqual(agent_id, "agt_shopper")

  def test_refuses_other_human_when_demo_rebind_disabled(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id": "agt_shopper",
      "user_id": USER_A,
      "enabled": True,
      "allowed_modes": ["live"],
    }
    with patch.dict(
      "os.environ",
      {"AGENT_TOKEN_SHOPPER": TOKEN, "LEASH_DEMO_REBIND": "0"},
      clear=False,
    ):
      with self.assertRaises(AuthorityError) as err:
        ensure_cluster_shopper(conn, USER_B, "live")
    self.assertEqual(err.exception.status, 409)
    self.assertIn("operator must provision", err.exception.detail)

  def test_idle_token_does_not_transfer_even_with_legacy_demo_flag(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id":"agt_shopper","user_id":USER_A,"enabled":True,"allowed_modes":["live"]}
    with patch.dict("os.environ",{"AGENT_TOKEN_SHOPPER":TOKEN,"LEASH_DEMO_REBIND":"1"}), patch("principals.bind_agent") as bind:
      with self.assertRaises(AuthorityError) as err:
        ensure_cluster_shopper(conn,USER_B,"live")
    self.assertEqual(err.exception.status,409)
    bind.assert_not_called()

  def test_scripted_mode_uses_scripted_env(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id": "agt_shopper_scripted",
      "user_id": USER_A,
      "enabled": True,
      "allowed_modes": ["scripted"],
    }
    with patch.dict(
      "os.environ",
      {"AGENT_TOKEN_SHOPPER_SCRIPTED": TOKEN, "LEASH_DEMO_REBIND": "0"},
      clear=False,
    ):
      self.assertEqual(
        ensure_cluster_shopper(conn, USER_A, "scripted"),
        "agt_shopper_scripted",
      )


if __name__ == "__main__":
  unittest.main()
