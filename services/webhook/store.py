"""Atomic local-rail authority, idempotency and event state; Valkey I/O only."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from decide import AuthorityState, Decision, GrantSnapshot

GRANT_KEY = "leash:grant:{grant_id}"
INSTRUMENT_KEY = "leash:instrument:{token}"
EVENT_KEY = "leash:local:event:{event_id}"
KILLSWITCH_KEY = "leash:killswitch"  # legacy operator/test global stop
MANDATE_KEY = "leash:mandate:{mandate_id}"
USER_KILL_KEY = "leash:killswitch:{user_id}"
USER_GRANTS_KEY = "leash:user-grants:{user_id}"
EVENT_STREAM = "leash:rail-events"


def grant_to_dict(grant: GrantSnapshot) -> dict[str, Any]:
  data = asdict(grant)
  data["expires_at"] = grant.expires_at.astimezone(timezone.utc).isoformat()
  return data


def grant_from_dict(data: dict[str, Any]) -> GrantSnapshot:
  fields = {k: data[k] for k in GrantSnapshot.__dataclass_fields__ if k in data}
  fields["mandate_version"] = int(fields["mandate_version"])
  fields["authorized_amount_cents"] = int(fields["authorized_amount_cents"])
  fields["expires_at"] = datetime.fromisoformat(fields["expires_at"].replace("Z", "+00:00"))
  return GrantSnapshot(**fields)


def event_fingerprint(payload: dict[str, Any]) -> str:
  return hashlib.sha256(
    json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
  ).hexdigest()


def decoded(raw: str) -> Decision:
  return Decision(**json.loads(raw))


@dataclass(frozen=True)
class CachedEvent:
  fingerprint: str
  decision: Decision


class GrantStore(Protocol):
  def get_event(self, event_id: str) -> CachedEvent | None: ...
  def get_grant_by_instrument(self, instrument_token: str) -> GrantSnapshot | None: ...
  def load_state(self, grant: GrantSnapshot | None) -> AuthorityState: ...
  def commit_decision(self, **kwargs) -> tuple[str, Decision]: ...


class MemoryGrantStore:
  """Explicit unit-test/local-only adapter; never a silent deployment fallback."""

  def __init__(self):
    self._lock = threading.Lock()
    self._grants = {}
    self._instruments = {}
    self._events = {}
    self._mandates = {}
    self._killswitch = False
    self._user_kills = set()
    self._purchases = {}
    self.audit_events = []

  def put_grant(self, grant: GrantSnapshot):
    with self._lock:
      old = self._grants.get(grant.grant_id)
      if old is not None or grant.instrument_token in self._instruments:
        if old == grant_to_dict(grant) and old["status"] == "ISSUED":
          return
        raise ValueError("Grant/instrument already bound")
      self._grants[grant.grant_id] = grant_to_dict(grant)
      self._instruments[grant.instrument_token] = grant.grant_id

  def get_grant(self, grant_id):
    with self._lock:
      raw = self._grants.get(grant_id)
      return grant_from_dict(raw) if raw else None

  def get_grant_by_instrument(self, instrument_token):
    with self._lock:
      raw = self._grants.get(self._instruments.get(instrument_token))
      return grant_from_dict(raw) if raw else None

  def set_mandate(self, mandate_id, *, status, version):
    with self._lock:
      old = self._mandates.get(mandate_id)
      if old and (
        version < old["version"]
        or (version == old["version"] and old["status"] != "active" and status == "active")
      ):
        raise ValueError("Cannot restore invalidated authority")
      self._mandates[mandate_id] = {"status": status, "version": version}

  def set_killswitch(self, on):
    with self._lock:
      self._killswitch = on

  def stop_user(self, user_id):
    with self._lock:
      self._user_kills.add(user_id)
      revoked = 0
      for grant in self._grants.values():
        if grant.get("user_id") == user_id and grant["status"] == "ISSUED":
          grant["status"] = "REVOKED"
          revoked += 1
      self.audit_events.append(
        {"type": "killswitch.changed", "user_id": user_id, "revoked": revoked}
      )
      return revoked

  def _state(self, grant):
    authority = self._mandates.get(grant.mandate_id, {}) if grant else {}
    return AuthorityState(
      killswitch_on=self._killswitch or bool(grant and grant.user_id in self._user_kills),
      mandate_status=authority.get("status", "missing"),
      current_mandate_version=authority.get("version", 0),
    )

  def load_state(self, grant):
    with self._lock:
      return self._state(grant)

  def get_event(self, event_id):
    with self._lock:
      return self._events.get(event_id)

  def commit_decision(
    self, *, grant_id, event_id, fingerprint, decision, consume, now=None, grant=None
  ):
    with self._lock:
      cached = self._events.get(event_id)
      if cached:
        return (
          ("duplicate", cached.decision)
          if cached.fingerprint == fingerprint
          else ("mismatch", Decision("ERROR", "event_payload_mismatch"))
        )
      if consume:
        raw = self._grants.get(grant_id)
        state = self._state(grant)
        reason = None
        if state.killswitch_on:
          reason = "killswitch_on"
        elif raw is None:
          reason = "no_grant"
        elif raw["status"] != "ISSUED":
          reason = {
            "CONSUMED": "grant_consumed",
            "REVOKED": "grant_revoked",
            "EXPIRED": "grant_expired",
          }.get(raw["status"], "invalid_grant_state")
        elif (now or datetime.now(timezone.utc)) >= datetime.fromisoformat(raw["expires_at"]):
          reason = "grant_expired"
        elif state.mandate_status != "active":
          reason = "mandate_inactive"
        elif state.current_mandate_version != raw["mandate_version"]:
          reason = "mandate_version_mismatch"
        elif grant is None or raw != grant_to_dict(grant):
          reason = "grant_changed"
        elif self._purchases.get((grant.mandate_id, grant.mandate_version), 0) >= 1:
          reason = "purchase_scope_exhausted"
        if reason:
          decision = Decision("DECLINED", reason)
        else:
          raw["status"] = "CONSUMED"
          self._purchases[(grant.mandate_id, grant.mandate_version)] = 1
      self._events[event_id] = CachedEvent(fingerprint, decision)
      self.audit_events.append(
        {"event_id": event_id, "user_id": grant.user_id if grant else "", **decision.as_dict()}
      )
      return "ok", decision

  def ping(self):
    return True


_CONSUME_LUA = """
if redis.call('EXISTS',KEYS[2]) == 1 then
  if redis.call('HGET',KEYS[2],'fingerprint') ~= ARGV[1] then return {'mismatch',''} end
  return {'duplicate',redis.call('HGET',KEYS[2],'decision')}
end
local stream_type = redis.call('TYPE',KEYS[5]).ok
if stream_type ~= 'none' and stream_type ~= 'stream' then return {'store_error',''} end
local committed = ARGV[2]
if ARGV[3] == '1' then
  local reason = nil
  local current = redis.call('HGET',KEYS[1],'status')
  local tm = redis.call('TIME')
  local clock = tonumber(tm[1]) + tonumber(tm[2])/1000000
  if redis.call('GET',KEYS[3]) == '1' or redis.call('GET',KEYS[6]) == '1' then reason='killswitch_on'
  elseif not current then reason='no_grant'
  elseif current == 'REVOKED' then reason='grant_revoked'
  elseif current == 'CONSUMED' then reason='grant_consumed'
  elseif current == 'EXPIRED' then reason='grant_expired'
  elseif current ~= 'ISSUED' then reason='invalid_grant_state'
  elseif clock >= tonumber(redis.call('HGET',KEYS[1],'expires_epoch') or '0') then reason='grant_expired'
  elseif redis.call('HGET',KEYS[4],'status') ~= 'active' then reason='mandate_inactive'
  elseif redis.call('HGET',KEYS[4],'version') ~= redis.call('HGET',KEYS[1],'mandate_version') then reason='mandate_version_mismatch'
  elseif redis.call('HGET',KEYS[1],'binding_fingerprint') ~= ARGV[4] then reason='grant_changed'
  elseif tonumber(redis.call('HGET',KEYS[4],'used:'..redis.call('HGET',KEYS[1],'mandate_version')) or '0') >= 1 then reason='purchase_scope_exhausted'
  end
  if reason then committed='{"result":"DECLINED","reason":"'..reason..'","rail":"local_payment_rail_simulator"}' 
  else redis.call('HSET',KEYS[1],'status','CONSUMED'); redis.call('HSET',KEYS[4],'used:'..redis.call('HGET',KEYS[1],'mandate_version'),'1') end
end
redis.call('HSET',KEYS[2],'fingerprint',ARGV[1],'decision',committed)
redis.call('XADD',KEYS[5],'*','type','authorization.decided','event_id',ARGV[5],'user_id',ARGV[6],'decision',committed)
return {'ok',committed}
"""

_PUT_LUA = """
if redis.call('EXISTS',KEYS[1]) == 1 or redis.call('EXISTS',KEYS[2]) == 1 then
  if redis.call('HGET',KEYS[1],'binding_fingerprint') == ARGV[1] and redis.call('HGET',KEYS[1],'status') == 'ISSUED' then return 'duplicate' end
  return 'conflict'
end
local index_type=redis.call('TYPE',KEYS[3]).ok
if index_type ~= 'none' and index_type ~= 'set' then return 'conflict' end
if redis.call('GET',KEYS[4]) == '1' then return 'conflict' end
for i=4,#ARGV,2 do redis.call('HSET',KEYS[1],ARGV[i],ARGV[i+1]) end
redis.call('HSET',KEYS[1],'binding_fingerprint',ARGV[1],'expires_epoch',ARGV[2])
redis.call('SET',KEYS[2],ARGV[3])
redis.call('SADD',KEYS[3],ARGV[3])
return 'ok'
"""

_MANDATE_LUA = """
local oldversion = tonumber(redis.call('HGET',KEYS[1],'version') or '0')
local oldstatus = redis.call('HGET',KEYS[1],'status')
if tonumber(ARGV[2]) < oldversion or (tonumber(ARGV[2]) == oldversion and oldstatus ~= 'active' and ARGV[1] == 'active') then return 'conflict' end
redis.call('HSET',KEYS[1],'status',ARGV[1],'version',ARGV[2])
return 'ok'
"""

_USER_KILL_LUA = """
redis.call('SET',KEYS[1],'1')
local revoked=0
for _,id in ipairs(redis.call('SMEMBERS',KEYS[2])) do
  local key='leash:grant:'..id
  if redis.call('HGET',key,'status') == 'ISSUED' then redis.call('HSET',key,'status','REVOKED'); revoked=revoked+1 end
end
redis.call('XADD',KEYS[3],'*','type','killswitch.changed','user_id',ARGV[1],'revoked',tostring(revoked))
return revoked
"""


class RedisGrantStore:
  def __init__(self, url):
    import redis

    self._r = redis.Redis.from_url(
      url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
    )
    self._script = self._r.register_script(_CONSUME_LUA)

  def put_grant(self, grant):
    data = grant_to_dict(grant)
    fields = [value for key, item in data.items() for value in (key, str(item))]
    result = self._r.eval(
      _PUT_LUA,
      4,
      GRANT_KEY.format(grant_id=grant.grant_id),
      INSTRUMENT_KEY.format(token=grant.instrument_token),
      USER_GRANTS_KEY.format(user_id=grant.user_id),
      USER_KILL_KEY.format(user_id=grant.user_id),
      event_fingerprint(data),
      str(grant.expires_at.timestamp()),
      grant.grant_id,
      *fields,
    )
    if result == "conflict":
      raise ValueError("Grant/instrument already bound")

  def get_grant(self, grant_id):
    data = self._r.hgetall(GRANT_KEY.format(grant_id=grant_id))
    return grant_from_dict(data) if data else None

  def get_grant_by_instrument(self, instrument_token):
    gid = self._r.get(INSTRUMENT_KEY.format(token=instrument_token))
    return self.get_grant(gid) if gid else None

  def set_mandate(self, mandate_id, *, status, version):
    result = self._r.eval(
      _MANDATE_LUA, 1, MANDATE_KEY.format(mandate_id=mandate_id), status, version
    )
    if result == "conflict":
      raise ValueError("Cannot restore invalidated authority")

  def set_killswitch(self, on):
    self._r.set(KILLSWITCH_KEY, "1" if on else "0")

  def stop_user(self, user_id):
    return int(
      self._r.eval(
        _USER_KILL_LUA,
        3,
        USER_KILL_KEY.format(user_id=user_id),
        USER_GRANTS_KEY.format(user_id=user_id),
        EVENT_STREAM,
        user_id,
      )
    )

  def load_state(self, grant):
    kill = self._r.get(KILLSWITCH_KEY) == "1" or bool(
      grant and self._r.get(USER_KILL_KEY.format(user_id=grant.user_id)) == "1"
    )
    raw = self._r.hgetall(MANDATE_KEY.format(mandate_id=grant.mandate_id)) if grant else {}
    return AuthorityState(kill, raw.get("status", "missing"), int(raw.get("version", 0)))

  def get_event(self, event_id):
    raw = self._r.hgetall(EVENT_KEY.format(event_id=event_id))
    return CachedEvent(raw["fingerprint"], decoded(raw["decision"])) if raw else None

  def commit_decision(
    self, *, grant_id, event_id, fingerprint, decision, consume, now=None, grant=None
  ):
    try:
      status, payload = self._script(
        keys=[
          GRANT_KEY.format(grant_id=grant_id or "_none"),
          EVENT_KEY.format(event_id=event_id),
          KILLSWITCH_KEY,
          MANDATE_KEY.format(mandate_id=grant.mandate_id if grant else "_none"),
          EVENT_STREAM,
          USER_KILL_KEY.format(user_id=grant.user_id if grant else "_none"),
        ],
        args=[
          fingerprint,
          json.dumps(decision.as_dict()),
          "1" if consume else "0",
          event_fingerprint(grant_to_dict(grant)) if grant else "",
          event_id,
          grant.user_id if grant else "",
        ],
      )
      if status in {"ok", "duplicate"}:
        return status, decoded(payload)
      if status == "mismatch":
        return status, Decision("ERROR", "event_payload_mismatch")
    except Exception:
      pass  # Never include provider/Redis exception text in logs or responses.
    return "store_error", Decision("ERROR", "state_store_unavailable")

  def ping(self):
    try:
      return bool(self._r.ping())
    except Exception:
      return False
