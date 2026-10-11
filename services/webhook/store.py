"""Atomic local-rail authority, idempotency and event state; Valkey I/O only."""

from __future__ import annotations

import hashlib
import json
import threading
from uuid import uuid4
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Protocol

from decide import AuthorityState, Decision, GrantSnapshot

GRANT_KEY = "leash:grant:{grant_id}"
INSTRUMENT_KEY = "leash:instrument:{token}"
EVENT_KEY = "leash:{event_scope}:event:{event_id}"
KILLSWITCH_KEY = "leash:killswitch"  # legacy operator/test global stop
MANDATE_KEY = "leash:mandate:{mandate_id}"
USER_KILL_KEY = "leash:killswitch:{user_id}"
USER_GRANTS_KEY = "leash:user-grants:{user_id}"
RUN_KILL_KEY = "leash:run-stop:{run_id}"
RUN_GRANTS_KEY = "leash:run-grants:{run_id}"
EVENT_STREAM = "leash:rail-events"
EXECUTION_EPOCH = "leash:execution:epoch"
RUN_KEY = "leash:execution:run:{run_id}"


def grant_to_dict(grant: GrantSnapshot) -> dict[str, Any]:
  data = asdict(grant)
  data["expires_at"] = grant.expires_at.astimezone(timezone.utc).isoformat()
  return data


def grant_from_dict(data: dict[str, Any]) -> GrantSnapshot:
  fields = {k: data[k] for k in GrantSnapshot.__dataclass_fields__ if k in data}
  fields["mandate_version"] = int(fields["mandate_version"])
  fields["authorized_amount_cents"] = int(fields["authorized_amount_cents"])
  fields["execution_generation"] = int(fields.get("execution_generation", 0))
  fields["expires_at"] = datetime.fromisoformat(fields["expires_at"].replace("Z", "+00:00"))
  fields.setdefault("run_id", "")
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
  def get_event(self, event_id: str, *, event_scope: str = "local") -> CachedEvent | None: ...
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
    self._run_kills = set()
    self._run_grants: dict[str, set[str]] = {}
    self._purchases = {}
    self.audit_events = []
    self._epoch = uuid4().hex
    self._runs = {}

  def epoch(self):
    return self._epoch

  def lease_run(self, run_id, user_id, generation, epoch, lease_until):
    with self._lock:
      old = self._runs.get(run_id)
      now = datetime.now(timezone.utc)
      if (epoch != self._epoch or user_id in self._user_kills
          or not now < lease_until <= now + timedelta(seconds=12)
          or old and (old['stopped'] or old['user_id'] != user_id or old['generation'] != generation
                      or old['lease_until'] <= now)):
        raise ValueError('Stale or stopped run')
      self._runs[run_id] = dict(user_id=user_id, generation=generation,
                                lease_until=lease_until, stopped=False)

  def stop_execution_run(self, run_id, user_id):
    with self._lock:
      old = self._runs.get(run_id)
      if old and old['user_id'] != user_id:
        raise ValueError('Run owner mismatch')
      self._runs[run_id] = {**(old or {}), 'user_id': user_id, 'stopped': True}
      self._run_kills.add(run_id)
      for grant in self._grants.values():
        if grant.get('run_id') == run_id and grant['status'] == 'ISSUED':
          grant['status'] = 'REVOKED'

  def _scope_valid(self, grant):
    if not grant.run_id or not grant.execution_generation:
      return True  # Local-rail and fixture grants; Graph grants carry a generation.
    scope = self._runs.get(grant.run_id)
    return bool(scope and not scope['stopped'] and scope['user_id'] == grant.user_id
      and scope['generation'] == grant.execution_generation and grant.rail_epoch == self._epoch
      and scope['lease_until'] > datetime.now(timezone.utc))

  def put_grant(self, grant: GrantSnapshot):
    with self._lock:
      if not self._scope_valid(grant):
        raise ValueError('Execution scope unavailable')
      if grant.user_id in self._user_kills:
        raise ValueError("User spending is stopped")
      if grant.run_id and grant.run_id in self._run_kills:
        raise ValueError("Run spending is stopped")
      old = self._grants.get(grant.grant_id)
      if old is not None or grant.instrument_token in self._instruments:
        if old == grant_to_dict(grant) and old["status"] == "ISSUED":
          return
        raise ValueError("Grant/instrument already bound")
      self._grants[grant.grant_id] = grant_to_dict(grant)
      self._instruments[grant.instrument_token] = grant.grant_id
      if grant.run_id:
        self._run_grants.setdefault(grant.run_id, set()).add(grant.grant_id)

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

  def stop_run(self, user_id: str, run_id: str) -> int:
    """Revoke unused grants for one run; latch blocks later installs for that run."""
    with self._lock:
      self._run_kills.add(run_id)
      revoked = 0
      for grant_id in list(self._run_grants.get(run_id, ())):
        grant = self._grants.get(grant_id)
        if (
          grant
          and grant.get("user_id") == user_id
          and grant.get("run_id") == run_id
          and grant["status"] == "ISSUED"
        ):
          grant["status"] = "REVOKED"
          revoked += 1
      self.audit_events.append(
        {
          "type": "run.stop.enforced",
          "user_id": user_id,
          "run_id": run_id,
          "revoked": revoked,
        }
      )
      return revoked

  def _state(self, grant):
    authority = self._mandates.get(grant.mandate_id, {}) if grant else {}
    run_stopped = bool(grant and grant.run_id and grant.run_id in self._run_kills)
    return AuthorityState(
      killswitch_on=self._killswitch
      or bool(grant and grant.user_id in self._user_kills)
      or run_stopped,
      mandate_status=authority.get("status", "missing"),
      current_mandate_version=authority.get("version", 0),
    )

  def load_state(self, grant):
    with self._lock:
      return self._state(grant)

  def get_event(self, event_id, *, event_scope="local"):
    with self._lock:
      return self._events.get((event_scope, event_id))

  def commit_decision(
    self,
    *,
    grant_id,
    event_id,
    fingerprint,
    decision,
    consume,
    now=None,
    grant=None,
    event_scope="local",
    event_record=None,
  ):
    with self._lock:
      cached = self._events.get((event_scope, event_id))
      if cached:
        return (
          ("duplicate", cached.decision)
          if cached.fingerprint == fingerprint
          else ("mismatch", Decision("ERROR", "event_payload_mismatch", rail=decision.rail))
        )
      if consume:
        raw = self._grants.get(grant_id)
        state = self._state(grant)
        reason = None
        if state.killswitch_on:
          reason = "killswitch_on"
        elif grant and not self._scope_valid(grant):
          reason = "execution_scope_revoked_or_expired"
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
          decision = Decision("DECLINED", reason, rail=decision.rail)
        else:
          raw["status"] = "CONSUMED"
          self._purchases[(grant.mandate_id, grant.mandate_version)] = 1
      self._events[(event_scope, event_id)] = CachedEvent(fingerprint, decision)
      self.audit_events.append(
        {
          "event_id": event_id,
          "user_id": grant.user_id if grant else "",
          **decision.as_dict(),
          "record_context": event_record,
        }
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
  -- Graph executions carry a generation >= 1; local-rail grants carry 0.
  local generation = redis.call('HGET',KEYS[1],'execution_generation') or ''
  if redis.call('GET',KEYS[3]) == '1' or redis.call('GET',KEYS[6]) == '1' or redis.call('GET',KEYS[7]) == '1' then reason='killswitch_on'
  elseif not current then reason='no_grant'
  elseif current == 'REVOKED' then reason='grant_revoked'
  elseif current == 'CONSUMED' then reason='grant_consumed'
  elseif current == 'EXPIRED' then reason='grant_expired'
  elseif current ~= 'ISSUED' then reason='invalid_grant_state'
  elseif clock >= tonumber(redis.call('HGET',KEYS[1],'expires_epoch') or '0') then reason='grant_expired'
  elseif redis.call('HGET',KEYS[4],'status') ~= 'active' then reason='mandate_inactive'
  elseif redis.call('HGET',KEYS[4],'version') ~= redis.call('HGET',KEYS[1],'mandate_version') then reason='mandate_version_mismatch'
  elseif redis.call('HGET',KEYS[1],'binding_fingerprint') ~= ARGV[4] then reason='grant_changed'
  elseif generation ~= '' and generation ~= '0' and (
    redis.call('GET',KEYS[9]) ~= redis.call('HGET',KEYS[1],'rail_epoch') or
    redis.call('HGET',KEYS[8],'stopped') ~= '0' or
    redis.call('HGET',KEYS[8],'generation') ~= generation or
    redis.call('HGET',KEYS[8],'user_id') ~= ARGV[6] or
    tonumber(redis.call('HGET',KEYS[8],'lease_until') or '0') <= clock
  ) then reason='execution_scope_revoked_or_expired'
  elseif tonumber(redis.call('HGET',KEYS[4],'used:'..redis.call('HGET',KEYS[1],'mandate_version')) or '0') >= 1 then reason='purchase_scope_exhausted'
  end
  if reason then committed='{"result":"DECLINED","reason":"'..reason..'","rail":"'..ARGV[7]..'"}'
  else redis.call('HSET',KEYS[1],'status','CONSUMED'); redis.call('HSET',KEYS[4],'used:'..redis.call('HGET',KEYS[1],'mandate_version'),'1') end
end
redis.call('HSET',KEYS[2],'fingerprint',ARGV[1],'decision',committed)
redis.call('XADD',KEYS[5],'*','type','authorization.decided','event_id',ARGV[5],'user_id',ARGV[6],'decision',committed,'record_context',ARGV[8])
return {'ok',committed}
"""

_PUT_LUA = """
local generation, epoch = '', ''
for i=5,#ARGV,2 do
  if ARGV[i]=='execution_generation' then generation=ARGV[i+1] end
  if ARGV[i]=='rail_epoch' then epoch=ARGV[i+1] end
end
if ARGV[4] ~= '' and generation ~= '' and generation ~= '0' then
  local tm=redis.call('TIME'); local clock=tonumber(tm[1])+tonumber(tm[2])/1000000
  if redis.call('GET',KEYS[8]) ~= epoch or redis.call('HGET',KEYS[7],'stopped') ~= '0' or
    redis.call('HGET',KEYS[7],'generation') ~= generation or
    tonumber(redis.call('HGET',KEYS[7],'lease_until') or '0') <= clock then return 'conflict' end
end
if redis.call('EXISTS',KEYS[1]) == 1 or redis.call('EXISTS',KEYS[2]) == 1 then
  if redis.call('HGET',KEYS[1],'binding_fingerprint') == ARGV[1] and redis.call('HGET',KEYS[1],'status') == 'ISSUED' then return 'duplicate' end
  return 'conflict'
end
local index_type=redis.call('TYPE',KEYS[3]).ok
if index_type ~= 'none' and index_type ~= 'set' then return 'conflict' end
local run_index_type=redis.call('TYPE',KEYS[6]).ok
if run_index_type ~= 'none' and run_index_type ~= 'set' then return 'conflict' end
if redis.call('GET',KEYS[4]) == '1' then return 'conflict' end
if redis.call('GET',KEYS[5]) == '1' then return 'conflict' end
for i=5,#ARGV,2 do redis.call('HSET',KEYS[1],ARGV[i],ARGV[i+1]) end
redis.call('HSET',KEYS[1],'binding_fingerprint',ARGV[1],'expires_epoch',ARGV[2])
redis.call('SET',KEYS[2],ARGV[3])
redis.call('SADD',KEYS[3],ARGV[3])
if ARGV[4] ~= '' then redis.call('SADD',KEYS[6],ARGV[3]) end
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

_RUN_LEASE_LUA = """
local tm=redis.call('TIME'); local clock=tonumber(tm[1])+tonumber(tm[2])/1000000
if redis.call('GET',KEYS[2]) ~= ARGV[3] or redis.call('GET',KEYS[3]) == '1' or
  tonumber(ARGV[4]) <= clock or tonumber(ARGV[4]) > clock+12 then return 'conflict' end
if redis.call('EXISTS',KEYS[1]) == 1 and (
  redis.call('HGET',KEYS[1],'stopped') ~= '0' or redis.call('HGET',KEYS[1],'user_id') ~= ARGV[1] or
  redis.call('HGET',KEYS[1],'generation') ~= ARGV[2] or
  tonumber(redis.call('HGET',KEYS[1],'lease_until') or '0') <= clock) then return 'conflict' end
redis.call('HSET',KEYS[1],'user_id',ARGV[1],'generation',ARGV[2],'lease_until',ARGV[4],'stopped','0')
return 'ok'
"""

_RUN_STOP_LUA = """
local owner=redis.call('HGET',KEYS[1],'user_id')
if owner and owner ~= ARGV[1] then return 'conflict' end
redis.call('HSET',KEYS[1],'user_id',ARGV[1],'stopped','1')
redis.call('SET',KEYS[3],'1')
for _,id in ipairs(redis.call('SMEMBERS',KEYS[2])) do
  local key='leash:grant:'..id
  if redis.call('HGET',key,'run_id') == ARGV[2] and redis.call('HGET',key,'status') == 'ISSUED' then
    redis.call('HSET',key,'status','REVOKED')
  end
end
return 'ok'
"""

_RUN_KILL_LUA = """
redis.call('SET',KEYS[1],'1')
local revoked=0
for _,id in ipairs(redis.call('SMEMBERS',KEYS[2])) do
  local key='leash:grant:'..id
  if redis.call('HGET',key,'status') == 'ISSUED'
     and redis.call('HGET',key,'user_id') == ARGV[1]
     and redis.call('HGET',key,'run_id') == ARGV[2] then
    redis.call('HSET',key,'status','REVOKED'); revoked=revoked+1
  end
end
redis.call('XADD',KEYS[3],'*','type','run.stop.enforced','user_id',ARGV[1],'run_id',ARGV[2],'revoked',tostring(revoked))
return revoked
"""


class RedisGrantStore:
  def __init__(self, url):
    import redis

    self._r = redis.Redis.from_url(
      url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
    )
    self._script = self._r.register_script(_CONSUME_LUA)

  def epoch(self):
    self._r.set(EXECUTION_EPOCH, uuid4().hex, nx=True)
    return self._r.get(EXECUTION_EPOCH)

  def lease_run(self, run_id, user_id, generation, epoch, lease_until):
    result = self._r.eval(_RUN_LEASE_LUA, 3, RUN_KEY.format(run_id=run_id), EXECUTION_EPOCH,
      USER_KILL_KEY.format(user_id=user_id), user_id, generation, epoch, lease_until.timestamp())
    if result != 'ok':
      raise ValueError('Stale or stopped run')

  def stop_execution_run(self, run_id, user_id):
    result = self._r.eval(_RUN_STOP_LUA, 3, RUN_KEY.format(run_id=run_id),
      USER_GRANTS_KEY.format(user_id=user_id), RUN_KILL_KEY.format(run_id=run_id), user_id, run_id)
    if result != 'ok':
      raise ValueError('Run owner mismatch')

  def put_grant(self, grant):
    data = grant_to_dict(grant)
    fields = [value for key, item in data.items() for value in (key, str(item))]
    run_id = grant.run_id or ""
    result = self._r.eval(
      _PUT_LUA,
      8,
      GRANT_KEY.format(grant_id=grant.grant_id),
      INSTRUMENT_KEY.format(token=grant.instrument_token),
      USER_GRANTS_KEY.format(user_id=grant.user_id),
      USER_KILL_KEY.format(user_id=grant.user_id),
      RUN_KILL_KEY.format(run_id=run_id or "_none"),
      RUN_GRANTS_KEY.format(run_id=run_id or "_none"),
      RUN_KEY.format(run_id=run_id or "_none"),
      EXECUTION_EPOCH,
      event_fingerprint(data),
      str(grant.expires_at.timestamp()),
      grant.grant_id,
      run_id,
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

  def stop_run(self, user_id: str, run_id: str) -> int:
    return int(
      self._r.eval(
        _RUN_KILL_LUA,
        3,
        RUN_KILL_KEY.format(run_id=run_id),
        RUN_GRANTS_KEY.format(run_id=run_id),
        EVENT_STREAM,
        user_id,
        run_id,
      )
    )

  def load_state(self, grant):
    kill = self._r.get(KILLSWITCH_KEY) == "1" or bool(
      grant and self._r.get(USER_KILL_KEY.format(user_id=grant.user_id)) == "1"
    ) or bool(
      grant and grant.run_id and self._r.get(RUN_KILL_KEY.format(run_id=grant.run_id)) == "1"
    )
    raw = self._r.hgetall(MANDATE_KEY.format(mandate_id=grant.mandate_id)) if grant else {}
    return AuthorityState(kill, raw.get("status", "missing"), int(raw.get("version", 0)))

  def get_event(self, event_id, *, event_scope="local"):
    raw = self._r.hgetall(EVENT_KEY.format(event_id=event_id, event_scope=event_scope))
    return CachedEvent(raw["fingerprint"], decoded(raw["decision"])) if raw else None

  def commit_decision(
    self,
    *,
    grant_id,
    event_id,
    fingerprint,
    decision,
    consume,
    now=None,
    grant=None,
    event_scope="local",
    event_record=None,
  ):
    try:
      status, payload = self._script(
        keys=[
          GRANT_KEY.format(grant_id=grant_id or "_none"),
          EVENT_KEY.format(event_id=event_id, event_scope=event_scope),
          KILLSWITCH_KEY,
          MANDATE_KEY.format(mandate_id=grant.mandate_id if grant else "_none"),
          EVENT_STREAM,
          USER_KILL_KEY.format(user_id=grant.user_id if grant else "_none"),
          RUN_KILL_KEY.format(run_id=grant.run_id if grant and grant.run_id else "_none"),
          RUN_KEY.format(run_id=grant.run_id if grant and grant.run_id else "_none"),
          EXECUTION_EPOCH,
        ],
        args=[
          fingerprint,
          json.dumps(decision.as_dict()),
          "1" if consume else "0",
          event_fingerprint(grant_to_dict(grant)) if grant else "",
          event_id,
          grant.user_id if grant else "",
          decision.rail,
          json.dumps(event_record or {}),
        ],
      )
      if status in {"ok", "duplicate"}:
        return status, decoded(payload)
      if status == "mismatch":
        return status, Decision("ERROR", "event_payload_mismatch", rail=decision.rail)
    except Exception:
      pass  # Never include provider/Redis exception text in logs or responses.
    return "store_error", Decision("ERROR", "state_store_unavailable", rail=decision.rail)

  def ping(self):
    try:
      return bool(self._r.ping())
    except Exception:
      return False
