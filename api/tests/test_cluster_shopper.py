"""Cluster shopper bind / demo idle-rebind for multi-user Mission Control demos."""

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
    self.assertIn("operator must rebind", err.exception.detail)

  def test_rebinds_idle_token_to_next_human(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id": "agt_shopper",
      "user_id": USER_A,
      "enabled": True,
      "allowed_modes": ["live"],
    }
    with (
      patch.dict(
        "os.environ",
        {"AGENT_TOKEN_SHOPPER": TOKEN, "LEASH_DEMO_REBIND": "1"},
        clear=False,
      ),
      patch("principals.user_has_active_shopper_run", return_value=False) as active,
      patch("principals.bind_agent") as bind,
    ):
      agent_id = ensure_cluster_shopper(conn, USER_B, "live")
    self.assertEqual(agent_id, "agt_shopper")
    active.assert_called_once_with(conn, USER_A)
    bind.assert_called_once_with(
      conn,
      user_id=USER_B,
      agent_id="agt_shopper",
      token=TOKEN,
      modes=("live",),
      allow_owner_transfer=True,
    )

  def test_refuses_rebind_while_prior_human_has_active_run(self):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "id": "agt_shopper",
      "user_id": USER_A,
      "enabled": True,
      "allowed_modes": ["live"],
    }
    with (
      patch.dict(
        "os.environ",
        {"AGENT_TOKEN_SHOPPER": TOKEN, "LEASH_DEMO_REBIND": "1"},
        clear=False,
      ),
      patch("principals.user_has_active_shopper_run", return_value=True),
      patch("principals.bind_agent") as bind,
    ):
      with self.assertRaises(AuthorityError) as err:
        ensure_cluster_shopper(conn, USER_B, "live")
    self.assertEqual(err.exception.status, 409)
    self.assertIn("active shopping run", err.exception.detail)
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
