"""Handler / Valkey protocol tests (C04) using the in-memory store."""

from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decide import AuthorizationAttempt, GrantSnapshot  # noqa: E402
from handler import authorize  # noqa: E402
from store import MemoryGrantStore  # noqa: E402

NOW = datetime(2026, 10, 10, 20, 0, 0, tzinfo=timezone.utc)


def _grant(**overrides) -> GrantSnapshot:
  base = dict(
    grant_id="grt_charger_01",
    status="ISSUED",
    mandate_id="mnd_charger_01",
    mandate_version=1,
    instrument_token="ins_charger_01",
    descriptor="VOLT SUPPLY CO",
    mcc="5732",
    authorized_amount_cents=2999,
    currency="USD",
    expires_at=datetime(2026, 10, 10, 20, 10, 0, tzinfo=timezone.utc),
  )
  base.update(overrides)
  return GrantSnapshot(**base)


def _auth(**overrides) -> AuthorizationAttempt:
  base = dict(
    event_id="auth_evt_0001",
    request_type="AUTHORIZATION",
    instrument_token="ins_charger_01",
    descriptor="VOLT SUPPLY CO",
    mcc="5732",
    amount_cents=2999,
    currency="USD",
  )
  base.update(overrides)
  return AuthorizationAttempt(**base)


class HandlerTests(unittest.TestCase):
  def setUp(self) -> None:
    self.store = MemoryGrantStore()
    self.store.put_grant(_grant())
    self.store.set_mandate("mnd_charger_01", status="active", version=1)

  def test_approve_then_duplicate_returns_same(self) -> None:
    first = authorize(self.store, _auth(), now=NOW)
    second = authorize(self.store, _auth(), now=NOW)
    self.assertEqual(first.result, "APPROVED")
    self.assertEqual(second.result, "APPROVED")
    self.assertEqual(first.reason, second.reason)
    self.assertEqual(self.store.get_grant("grt_charger_01").status, "CONSUMED")

  def test_same_event_different_payload_is_error(self) -> None:
    authorize(self.store, _auth(), now=NOW)
    again = authorize(self.store, _auth(amount_cents=2500), now=NOW)
    self.assertEqual(again.result, "ERROR")
    self.assertEqual(again.reason, "event_payload_mismatch")

  def test_concurrent_distinct_events_one_approval(self) -> None:
    a = _auth(event_id="auth_evt_a")
    b = _auth(event_id="auth_evt_b")

    def run(attempt: AuthorizationAttempt):
      return authorize(self.store, attempt, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
      results = list(pool.map(run, [a, b]))
    approved = [r for r in results if r.result == "APPROVED"]
    declined = [r for r in results if r.result == "DECLINED"]
    self.assertEqual(len(approved), 1)
    self.assertEqual(len(declined), 1)
    self.assertEqual(declined[0].reason, "grant_consumed")

  def test_killswitch_declines(self) -> None:
    self.store.set_killswitch(True)
    decision = authorize(self.store, _auth(), now=NOW)
    self.assertEqual(decision.result, "DECLINED")
    self.assertEqual(decision.reason, "killswitch_on")
    self.assertEqual(self.store.get_grant("grt_charger_01").status, "ISSUED")


if __name__ == "__main__":
  unittest.main()
