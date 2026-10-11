"""Run the same race/replay tests in memory and against an isolated real Redis/Valkey."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decide import AuthorizationAttempt, GrantSnapshot  # noqa: E402
from handler import authorize  # noqa: E402
from store import EVENT_STREAM, GRANT_KEY, MemoryGrantStore, RedisGrantStore  # noqa: E402

URL = os.getenv("LEASH_TEST_VALKEY_URL", "")


class AtomicStoreTests(unittest.TestCase):
  def setUp(self):
    self.store = MemoryGrantStore()
    self.prepare()

  def prepare(self):
    suffix = uuid4().hex
    self.grant = GrantSnapshot(
      "grt_" + suffix,
      "ISSUED",
      "mnd_" + suffix,
      1,
      "ins_" + suffix,
      "VOLT SUPPLY CO",
      "5732",
      2999,
      "USD",
      datetime.now(timezone.utc) + timedelta(minutes=10),
      "usr_" + suffix,
      "a" * 64,
      "chk_" + suffix,
      "b" * 64,
      "bind_" + suffix,
    )
    self.store.set_mandate(self.grant.mandate_id, status="active", version=1)
    self.store.put_grant(self.grant)
    self.attempt = AuthorizationAttempt(
      "evt_" + suffix,
      "AUTHORIZATION",
      self.grant.instrument_token,
      self.grant.descriptor,
      self.grant.mcc,
      2999,
      "USD",
      self.grant.checkout_id,
      self.grant.checkout_hash,
      self.grant.merchant_binding_id,
    )

  def test_stop_between_read_and_commit_declines_and_caches_original(self):
    original = self.store.commit_decision

    def stop_first(**kwargs):
      self.store.stop_user(self.grant.user_id)
      return original(**kwargs)

    with patch.object(self.store, "commit_decision", side_effect=stop_first):
      result = authorize(self.store, self.attempt)
    self.assertEqual(result.reason, "killswitch_on")
    self.assertEqual(authorize(self.store, self.attempt), result)
    self.assertEqual(self.store.get_grant(self.grant.grant_id).status, "REVOKED")

  def test_revocation_between_read_and_commit_declines(self):
    original = self.store.commit_decision

    def revoke_first(**kwargs):
      self.store.set_mandate(self.grant.mandate_id, status="revoked", version=1)
      return original(**kwargs)

    with patch.object(self.store, "commit_decision", side_effect=revoke_first):
      result = authorize(self.store, self.attempt)
    self.assertEqual(result.reason, "mandate_inactive")
    self.assertEqual(authorize(self.store, self.attempt), result)

  def test_missing_authority_never_approves(self):
    if isinstance(self.store, MemoryGrantStore):
      self.store._mandates.clear()
    else:
      self.store._r.delete("leash:mandate:" + self.grant.mandate_id)
    self.assertEqual(authorize(self.store, self.attempt).reason, "mandate_inactive")

  def test_distinct_concurrent_attempts_one_success_and_every_decision_cached(self):
    attempts = [replace(self.attempt, event_id="evt_" + uuid4().hex) for _ in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
      results = list(pool.map(lambda a: authorize(self.store, a), attempts))
    self.assertEqual(sum(r.result == "APPROVED" for r in results), 1)
    for attempt, result in zip(attempts, results):
      self.assertEqual(authorize(self.store, attempt), result)
    if isinstance(self.store, RedisGrantStore):
      self.assertEqual(self.store._r.xlen(EVENT_STREAM), 16)
    else:
      self.assertEqual(len(self.store.audit_events), 16)

  def test_consumed_grant_cannot_be_reseeded(self):
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    with self.assertRaises(ValueError):
      self.store.put_grant(self.grant)

  def test_revoked_mandate_cannot_be_reactivated_by_seed(self):
    self.store.set_mandate(self.grant.mandate_id, status="revoked", version=1)
    with self.assertRaises(ValueError):
      self.store.set_mandate(self.grant.mandate_id, status="active", version=1)

  def test_checkout_tampering_declines_even_same_merchant_amount(self):
    result = authorize(self.store, replace(self.attempt, checkout_id="chk_subscription"))
    self.assertEqual(result.reason, "checkout_binding_mismatch")
    self.assertEqual(self.store.get_grant(self.grant.grant_id).status, "ISSUED")

  def test_user_stop_does_not_stop_other_owner_or_reverse_authorization(self):
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    self.assertEqual(self.store.stop_user(self.grant.user_id), 0)
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    self.prepare()  # new owner, mandate, instrument and checkout
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")


@unittest.skipUnless(URL, "Set LEASH_TEST_VALKEY_URL to isolated localhost:56379/15")
class RealRedisAtomicTests(AtomicStoreTests):
  def setUp(self):
    parsed = urlparse(URL)
    if (
      parsed.hostname not in {"127.0.0.1", "localhost"}
      or parsed.port != 56379
      or parsed.path != "/15"
    ):
      raise RuntimeError("Refusing tests outside the isolated local rail test database")
    self.store = RedisGrantStore(URL)
    self.store._r.flushdb()
    self.prepare()

  def tearDown(self):
    self.store._r.flushdb()

  def test_expiry_between_policy_read_and_atomic_commit_uses_server_clock(self):
    original = self.store.commit_decision

    def expire_first(**kwargs):
      self.store._r.hset(GRANT_KEY.format(grant_id=self.grant.grant_id), "expires_epoch", "1")
      return original(**kwargs)

    with patch.object(self.store, "commit_decision", side_effect=expire_first):
      self.assertEqual(authorize(self.store, self.attempt).reason, "grant_expired")
