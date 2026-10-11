"""Durable rail-stream delivery to API audit, outside the authorization path."""

from __future__ import annotations

import json
import logging
import os
import threading
from uuid import uuid4

import httpx

from store import EVENT_STREAM, RedisGrantStore

logger = logging.getLogger("leash.webhook.activity")
CURSOR_KEY = "leash:rail-relay:cursor"
LEASE_KEY = "leash:rail-relay:lease"
QUARANTINE_KEY = "leash:rail-relay:quarantine"
ADVANCE = """
if redis.call('GET',KEYS[1]) ~= ARGV[1] then return 0 end
if (redis.call('GET',KEYS[2]) or '0-0') ~= ARGV[2] then return 0 end
redis.call('SET',KEYS[2],ARGV[3])
return 1
"""
RELEASE = """
if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end
return 0
"""


class ActivityRelay:
  """One fenced delivery at a time; replay after crash/outage is idempotent."""

  def __init__(self, store, api_url, token):
    self.store = store
    self.api_url = api_url.rstrip("/")
    self.token = token
    self.closed = threading.Event()
    self.thread = None

  def deliver_once(self):
    redis = self.store._r
    owner = uuid4().hex
    if not redis.set(LEASE_KEY, owner, nx=True, ex=10):
      return False
    try:
      cursor = redis.get(CURSOR_KEY) or "0-0"
      streams = redis.xread({EVENT_STREAM: cursor}, count=1)
      if not streams:
        return False
      entry_id, fields = streams[0][1][0]
      context = fields.get("record_context")
      if context:
        body = json.loads(context)
        if body.get("user_id"):
          body["data"].update(json.loads(fields["decision"]))
          with httpx.Client(timeout=2, follow_redirects=False) as client:
            response = client.post(
              self.api_url + "/internal/activity",
              headers={"Authorization": "Bearer " + self.token},
              json=body,
            )
          if response.status_code not in {201, 409}:
            if response.status_code != 422:
              return False  # Outages/configuration/auth errors remain pending.
            redis.hset(QUARANTINE_KEY, entry_id, "validation_rejected")
        else:
          redis.hset(QUARANTINE_KEY, entry_id, "owner_unresolved")
      elif fields.get("type") == "authorization.decided":
        # Old stream entries predate full context. Retain them for operator repair.
        redis.hset(QUARANTINE_KEY, entry_id, "legacy_context_missing")
      # killswitch.changed already commits through the human API transaction.
      return bool(redis.eval(ADVANCE, 2, LEASE_KEY, CURSOR_KEY, owner, cursor, entry_id))
    finally:
      redis.eval(RELEASE, 1, LEASE_KEY, owner)

  def start(self):
    def work():
      while not self.closed.is_set():
        try:
          delivered = self.deliver_once()
        except Exception:
          delivered = False
          logger.warning("Rail audit delivery pending; persisted stream retained")
        if not delivered:
          self.closed.wait(1)

    self.thread = threading.Thread(target=work, name="rail-audit-relay", daemon=True)
    self.thread.start()
    return self

  def stop(self):
    self.closed.set()
    if self.thread:
      self.thread.join(3)


def start_activity_relay(store: RedisGrantStore):
  api_url = os.getenv("API_URL", "").strip()
  token = os.getenv("RAIL_EVENT_TOKEN", "").strip()
  if not api_url or len(token) < 32 or token == os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip():
    return None  # Stream persists until an event-only credential is configured.
  return ActivityRelay(store, api_url, token).start()
