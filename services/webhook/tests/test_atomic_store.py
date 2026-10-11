"""Run the same race/replay tests in memory and against an isolated real Redis/Valkey."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
import httpx
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decide import AuthorizationAttempt, GrantSnapshot  # noqa: E402
from handler import authorize  # noqa: E402
from store import EVENT_STREAM, GRANT_KEY, MemoryGrantStore, RedisGrantStore  # noqa: E402
from activity_notify import ActivityRelay, CURSOR_KEY  # noqa: E402

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

  def test_two_grants_cannot_authorize_two_purchases_for_same_mandate_version(self):
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    second = replace(self.grant, grant_id="grt_second", instrument_token="ins_second")
    self.store.put_grant(second)
    attempt = replace(self.attempt, event_id="evt_second", instrument_token="ins_second")
    self.assertEqual(authorize(self.store, attempt).reason, "purchase_scope_exhausted")
    self.assertEqual(authorize(self.store, attempt).reason, "purchase_scope_exhausted")

  def test_asa_legacy_unbound_grant_still_cannot_approve(self):
    grant = replace(
      self.grant,
      checkout_id="",
      checkout_hash="",
      merchant_binding_id="",
      grant_id="grt_legacy",
      instrument_token="ins_legacy",
    )
    self.store.put_grant(grant)
    attempt = replace(
      self.attempt,
      event_id="evt_legacy",
      instrument_token="ins_legacy",
      checkout_id="",
      checkout_hash="",
      merchant_binding_id="",
    )
    result = authorize(self.store, attempt, event_scope="lithic")
    self.assertEqual(result.reason, "checkout_correlation_unavailable")
    self.assertEqual(self.store.get_grant(grant.grant_id).status, "ISSUED")

  def test_revoked_mandate_cannot_be_reactivated_by_seed(self):
    self.store.set_mandate(self.grant.mandate_id, status="revoked", version=1)
    with self.assertRaises(ValueError):
      self.store.set_mandate(self.grant.mandate_id, status="active", version=1)

  def test_checkout_tampering_declines_even_same_merchant_amount(self):
    result = authorize(self.store, replace(self.attempt, checkout_id="chk_subscription"))
    self.assertEqual(result.reason, "checkout_binding_mismatch")
    self.assertEqual(self.store.get_grant(self.grant.grant_id).status, "ISSUED")

  def test_decline_evidence_is_redacted_before_rail_stream_persistence(self):
    import json

    secret = "4242424242424242"
    self.assertEqual(
      authorize(self.store, replace(self.attempt, descriptor=secret)).result, "DECLINED"
    )
    if isinstance(self.store, RedisGrantStore):
      raw = self.store._r.xrange(EVENT_STREAM)[0][1]["record_context"]
    else:
      raw = json.dumps(self.store.audit_events[-1]["record_context"])
    self.assertNotIn(secret, raw)

  def test_user_stop_does_not_stop_other_owner_or_reverse_authorization(self):
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    self.assertEqual(self.store.stop_user(self.grant.user_id), 0)
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    self.prepare()  # new owner, mandate, instrument and checkout
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")

  def test_run_stop_revokes_only_that_run_and_blocks_reissue(self):
    run_a = "run_" + uuid4().hex
    run_b = "run_" + uuid4().hex
    scoped = replace(self.grant, run_id=run_a)
    # Replace the unscoped seed from prepare with a run-scoped grant.
    if isinstance(self.store, MemoryGrantStore):
      self.store._grants.clear()
      self.store._instruments.clear()
      self.store._run_grants.clear()
    else:
      self.store._r.flushdb()
      self.store.set_mandate(scoped.mandate_id, status="active", version=1)
    self.store.put_grant(scoped)
    other = replace(
      scoped,
      grant_id="grt_other",
      instrument_token="ins_other",
      run_id=run_b,
    )
    self.store.put_grant(other)
    self.assertEqual(self.store.stop_run(scoped.user_id, run_a), 1)
    self.assertEqual(self.store.get_grant(scoped.grant_id).status, "REVOKED")
    self.assertEqual(self.store.get_grant(other.grant_id).status, "ISSUED")
    declined = authorize(
      self.store,
      replace(self.attempt, instrument_token=scoped.instrument_token, event_id="evt_stopped"),
    )
    self.assertEqual(declined.reason, "killswitch_on")
    with self.assertRaises(ValueError):
      self.store.put_grant(replace(scoped, grant_id="grt_reissue", instrument_token="ins_reissue"))
    still_ok = authorize(
      self.store,
      replace(
        self.attempt,
        instrument_token=other.instrument_token,
        event_id="evt_other",
        checkout_id=other.checkout_id,
        checkout_hash=other.checkout_hash,
        merchant_binding_id=other.merchant_binding_id,
      ),
    )
    self.assertEqual(still_ok.result, "APPROVED")


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

  def test_wrong_stream_type_does_not_consume_or_cache_approval(self):
    self.store._r.set(EVENT_STREAM, "incorrect-type")
    self.assertEqual(authorize(self.store, self.attempt).reason, "state_store_unavailable")
    self.assertEqual(self.store.get_grant(self.grant.grant_id).status, "ISSUED")
    self.assertIsNone(self.store.get_event(self.attempt.event_id))

  def test_durable_relay_outage_and_crash_replay_deliver_original_once(self):
    self.assertEqual(authorize(self.store, self.attempt).result, "APPROVED")
    relay = ActivityRelay(self.store, "http://api.test", "event-only-" + "x" * 32)
    with patch("activity_notify.httpx.Client") as client:
      post = client.return_value.__enter__.return_value.post
      post.return_value = httpx.Response(503)
      self.assertFalse(relay.deliver_once())
      self.assertIsNone(self.store._r.get(CURSOR_KEY))
      post.return_value = httpx.Response(201)
      self.assertTrue(relay.deliver_once())
      original = post.call_args.kwargs["json"]
      self.assertEqual(original["data"]["result"], "APPROVED")
      self.assertEqual(original["user_id"], self.grant.user_id)
      self.store._r.delete(CURSOR_KEY)  # Crash after API commit, before cursor ack.
      post.return_value = httpx.Response(409)
      self.assertTrue(relay.deliver_once())
      self.assertEqual(post.call_args.kwargs["json"], original)
      self.assertFalse(relay.deliver_once())
    self.assertEqual(self.store._r.xlen(EVENT_STREAM), 1)
