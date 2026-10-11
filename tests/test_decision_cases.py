"""Run Aditya's rail-stage decision_cases.yaml against pure decide() (C03/C07)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "webhook"))

from decide import (  # noqa: E402
  AuthorityState,
  AuthorizationAttempt,
  GrantSnapshot,
  decide,
)

CASES_PATH = ROOT / "tests" / "decision_cases.yaml"
FIXED_NOW = datetime(2026, 10, 10, 20, 0, 0, tzinfo=timezone.utc)


def _parse_dt(value: str | None) -> datetime:
  if not value:
    return FIXED_NOW
  return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _grant(data: dict | None) -> GrantSnapshot | None:
  if data is None:
    return None
  return GrantSnapshot(
    grant_id=str(data["grant_id"]),
    status=str(data["status"]),
    mandate_id=str(data["mandate_id"]),
    mandate_version=int(data["mandate_version"]),
    instrument_token=str(data["instrument_token"]),
    descriptor=str(data["descriptor"]),
    mcc=str(data["mcc"]),
    authorized_amount_cents=int(data["authorized_amount_cents"]),
    currency=str(data["currency"]),
    expires_at=_parse_dt(str(data["expires_at"])),
  )


def _attempt(data: dict) -> AuthorizationAttempt:
  return AuthorizationAttempt(
    event_id=str(data["event_id"]),
    request_type=str(data["request_type"]),
    instrument_token=str(data["instrument_token"]),
    descriptor=str(data["descriptor"]),
    mcc=str(data["mcc"]),
    amount_cents=int(data["amount_cents"]),
    currency=str(data["currency"]),
  )


def _state(data: dict) -> AuthorityState:
  return AuthorityState(
    killswitch_on=bool(data.get("killswitch_on", False)),
    mandate_status=str(data.get("mandate_status", "active")),
    current_mandate_version=int(data.get("current_mandate_version", 1)),
  )


def load_rail_cases() -> list[dict]:
  doc = yaml.safe_load(CASES_PATH.read_text())
  return [c for c in doc["cases"] if c.get("stage") == "rail"]


class RailDecisionCases(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.cases = load_rail_cases()

  def test_all_rail_cases(self) -> None:
    self.assertGreaterEqual(len(self.cases), 10)
    failures: list[str] = []
    for case in self.cases:
      now = _parse_dt(case.get("now"))
      decision = decide(
        _attempt(case["authorization"]),
        _grant(case.get("grant")),
        _state(case["state"]),
        now=now,
      )
      expected = case["expected"]
      ok = True
      if "result" in expected and decision.result != expected["result"]:
        ok = False
      if "result_in" in expected and decision.result not in expected["result_in"]:
        ok = False
      if "reason" in expected and decision.reason != expected["reason"]:
        ok = False
      if not ok:
        failures.append(
          f"{case['name']}: got {decision.result}/{decision.reason}, expected {expected}"
        )
    self.assertEqual(failures, [], msg="\n".join(failures))


if __name__ == "__main__":
  unittest.main()
