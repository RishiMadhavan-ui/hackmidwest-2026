"""Unit tests for activity envelope shape (no Postgres required)."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: F401,E402
from datetime import datetime, timezone
from unittest.mock import MagicMock

from activity import ACCOUNT_CREATED, emit_activity
from leash_shared.events import EventType


class ActivityEmitTests(unittest.TestCase):
  def test_known_event_type_uses_audit_event(self):
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    # ensure_user SELECT after INSERT
    conn.execute.return_value.fetchone.return_value = {
      "auth_user_id": "12345678-1234-1234-1234-123456789abc",
    }
    record = emit_activity(
      conn,
      user_id="usr_12345678123412341234123456789abc",
      event_type=EventType.CARD_ISSUED.value,
      data={"last_four": "4242", "password": "should-redact"},
      auth_user_id="12345678-1234-1234-1234-123456789abc",
      at=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
    )
    self.assertEqual(record["type"], "card.issued")
    self.assertEqual(record["data"]["last_four"], "4242")
    self.assertEqual(record["data"]["password"], "[REDACTED]")
    self.assertTrue(record["event_id"].startswith("evt_"))

  def test_account_lifecycle_types_persist_without_event_enum(self):
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
      "auth_user_id": "12345678-1234-1234-1234-123456789abc",
    }
    record = emit_activity(
      conn,
      user_id="usr_12345678123412341234123456789abc",
      event_type=ACCOUNT_CREATED,
      data={"email": "a@example.com"},
      auth_user_id="12345678-1234-1234-1234-123456789abc",
    )
    self.assertEqual(record["type"], "account.created")
    self.assertEqual(record["data"]["email"], "a@example.com")


if __name__ == "__main__":
  unittest.main()
