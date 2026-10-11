"""Attack Lab operator boundary unit tests."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402

from authority_errors import AuthorityError  # noqa: E402
from attack_lab import require_attack_lab_operator, attack_lab_status, start_scenario  # noqa: E402
from principals import Principal  # noqa: E402


class AttackLabTests(unittest.TestCase):
  def test_authenticated_non_operator_is_forbidden(self) -> None:
    human = Principal("human", "usr_" + "a" * 32)
    with patch.dict("os.environ", {"ATTACK_LAB_OPERATOR_USER_IDS": "usr_" + "b" * 32}):
      with self.assertRaises(AuthorityError) as error:
        require_attack_lab_operator(human)
      self.assertEqual(error.exception.status, 403)

  def test_empty_allowlist_forbids_everyone(self) -> None:
    human = Principal("human", "usr_" + "a" * 32)
    with patch.dict("os.environ", {"ATTACK_LAB_OPERATOR_USER_IDS": ""}):
      with self.assertRaises(AuthorityError) as error:
        require_attack_lab_operator(human)
      self.assertEqual(error.exception.status, 403)

  def test_operator_status_and_scenario_gate(self) -> None:
    operator = Principal("human", "usr_" + "a" * 32)
    with patch.dict(
      "os.environ",
      {
        "ATTACK_LAB_OPERATOR_USER_IDS": operator.user_id,
        "ATTACK_LAB_TOKEN": "t" * 32,
        "STORE_URL": "http://store.test",
      },
    ):
      self.assertEqual(require_attack_lab_operator(operator).user_id, operator.user_id)
      status = attack_lab_status(operator)
      self.assertTrue(status["operator_authorized"])
      self.assertTrue(status["can_run_attacks"])
      with self.assertRaises(AuthorityError) as error:
        start_scenario("demo-subscription", operator)
      self.assertEqual(error.exception.status, 503)


if __name__ == "__main__":
  unittest.main()
