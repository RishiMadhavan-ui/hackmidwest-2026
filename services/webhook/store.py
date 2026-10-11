"""Valkey-backed grant / event / kill-switch state (C04).

Network I/O for the authorization handler is Valkey only. SQL and merchant
calls stay outside this path.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from decide import AuthorityState, Decision, GrantSnapshot

GRANT_KEY = "leash:grant:{grant_id}"
INSTRUMENT_KEY = "leash:instrument:{token}"
EVENT_KEY = "leash:event:{event_id}"
KILLSWITCH_KEY = "leash:killswitch"
MANDATE_KEY = "leash:mandate:{mandate_id}"

EVENT_TTL_SECONDS = 60 * 60 * 24
GRANT_TTL_SECONDS = 60 * 60 * 6


def _iso(dt: datetime) -> str:
  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
  return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime:
  text = value.replace("Z", "+00:00")
  return datetime.fromisoformat(text)


def grant_to_dict(grant: GrantSnapshot) -> dict[str, Any]:
  data = asdict(grant)
  data["expires_at"] = _iso(grant.expires_at)
  return data


def grant_from_dict(data: dict[str, Any]) -> GrantSnapshot:
  user_id = data.get("user_id") or None
  if user_id == "":
    user_id = None
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
    user_id=str(user_id) if user_id else None,
  )


def event_fingerprint(payload: dict[str, Any]) -> str:
  """Canonical fingerprint of the authorization attempt (no secrets)."""
  keys = (
    "event_id",
    "request_type",
    "instrument_token",
    "descriptor",
    "mcc",
    "amount_cents",
    "currency",
  )
  body = {k: payload[k] for k in keys}
  return json.dumps(body, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CachedEvent:
  fingerprint: str
  decision: Decision


class GrantStore(Protocol):
  def put_grant(self, grant: GrantSnapshot) -> None: ...
  def get_grant(self, grant_id: str) -> GrantSnapshot | None: ...
  def get_grant_by_instrument(self, instrument_token: str) -> GrantSnapshot | None: ...
  def set_killswitch(self, on: bool) -> None: ...
  def set_mandate(self, mandate_id: str, *, status: str, version: int) -> None: ...
  def load_state(self, grant: GrantSnapshot | None) -> AuthorityState: ...
  def get_event(self, event_id: str) -> CachedEvent | None: ...
  def commit_decision(
    self,
    *,
    grant_id: str | None,
    event_id: str,
    fingerprint: str,
    decision: Decision,
    consume: bool,
  ) -> tuple[str, Decision]:
    """Atomically record decision. Returns ('ok'|'duplicate'|'mismatch'|'lost_race'|'store_error', decision)."""
    ...

  def ping(self) -> bool: ...


class MemoryGrantStore:
  """In-process store for unit tests (serialized with a lock)."""

  def __init__(self) -> None:
    self._lock = threading.Lock()
    self._grants: dict[str, dict[str, Any]] = {}
    self._instruments: dict[str, str] = {}
    self._events: dict[str, dict[str, str]] = {}
    self._killswitch = False
    self._mandates: dict[str, dict[str, Any]] = {}

  def put_grant(self, grant: GrantSnapshot) -> None:
    with self._lock:
      self._grants[grant.grant_id] = grant_to_dict(grant)
      self._instruments[grant.instrument_token] = grant.grant_id

  def get_grant(self, grant_id: str) -> GrantSnapshot | None:
    with self._lock:
      raw = self._grants.get(grant_id)
      return grant_from_dict(raw) if raw else None

  def get_grant_by_instrument(self, instrument_token: str) -> GrantSnapshot | None:
    with self._lock:
      gid = self._instruments.get(instrument_token)
      if not gid:
        return None
      raw = self._grants.get(gid)
      return grant_from_dict(raw) if raw else None

  def set_killswitch(self, on: bool) -> None:
    with self._lock:
      self._killswitch = on

  def set_mandate(self, mandate_id: str, *, status: str, version: int) -> None:
    with self._lock:
      self._mandates[mandate_id] = {"status": status, "version": version}

  def load_state(self, grant: GrantSnapshot | None) -> AuthorityState:
    with self._lock:
      if grant is None:
        return AuthorityState(killswitch_on=self._killswitch)
      m = self._mandates.get(grant.mandate_id)
      if m is None:
        return AuthorityState(
          killswitch_on=self._killswitch,
          mandate_status="active",
          current_mandate_version=grant.mandate_version,
        )
      return AuthorityState(
        killswitch_on=self._killswitch,
        mandate_status=str(m["status"]),
        current_mandate_version=int(m["version"]),
      )

  def get_event(self, event_id: str) -> CachedEvent | None:
    with self._lock:
      raw = self._events.get(event_id)
      if not raw:
        return None
      d = json.loads(raw["decision"])
      return CachedEvent(
        fingerprint=raw["fingerprint"],
        decision=Decision(result=d["result"], reason=d["reason"], rail=d.get("rail", "local_payment_rail_simulator")),
      )

  def commit_decision(
    self,
    *,
    grant_id: str | None,
    event_id: str,
    fingerprint: str,
    decision: Decision,
    consume: bool,
  ) -> tuple[str, Decision]:
    with self._lock:
      existing = self._events.get(event_id)
      if existing is not None:
        if existing["fingerprint"] != fingerprint:
          return (
            "mismatch",
            Decision(result="ERROR", reason="event_payload_mismatch"),
          )
        d = json.loads(existing["decision"])
        return (
          "duplicate",
          Decision(result=d["result"], reason=d["reason"], rail=d.get("rail", "local_payment_rail_simulator")),
        )
      if consume:
        if not grant_id or grant_id not in self._grants:
          return "lost_race", Decision(result="DECLINED", reason="no_grant")
        if self._grants[grant_id]["status"] != "ISSUED":
          return "lost_race", Decision(result="DECLINED", reason="grant_consumed")
        self._grants[grant_id]["status"] = "CONSUMED"
      self._events[event_id] = {
        "fingerprint": fingerprint,
        "decision": json.dumps(decision.as_dict(), separators=(",", ":")),
      }
      return "ok", decision

  def ping(self) -> bool:
    return True


_CONSUME_LUA = """
local event_key = KEYS[1]
local grant_key = KEYS[2]
local fingerprint = ARGV[1]
local decision_json = ARGV[2]
local consume = ARGV[3]
local event_ttl = tonumber(ARGV[4])

if redis.call('EXISTS', event_key) == 1 then
  local prev_fp = redis.call('HGET', event_key, 'fingerprint')
  local prev_dec = redis.call('HGET', event_key, 'decision')
  if prev_fp ~= fingerprint then
    return {'mismatch', prev_dec}
  end
  return {'duplicate', prev_dec}
end

if consume == '1' then
  if redis.call('EXISTS', grant_key) == 0 then
    return {'lost_race', ''}
  end
  local status = redis.call('HGET', grant_key, 'status')
  if status ~= 'ISSUED' then
    return {'lost_race', status or ''}
  end
  redis.call('HSET', grant_key, 'status', 'CONSUMED')
end

redis.call('HSET', event_key, 'fingerprint', fingerprint, 'decision', decision_json)
redis.call('EXPIRE', event_key, event_ttl)
return {'ok', decision_json}
"""


class RedisGrantStore:
  """Valkey / Redis grant store using a Lua commit for atomic consume + cache."""

  def __init__(self, url: str) -> None:
    import redis

    self._r = redis.Redis.from_url(url, decode_responses=True)
    self._script = self._r.register_script(_CONSUME_LUA)

  def put_grant(self, grant: GrantSnapshot) -> None:
    key = GRANT_KEY.format(grant_id=grant.grant_id)
    pipe = self._r.pipeline()
    pipe.hset(
      key,
      mapping={
        "grant_id": grant.grant_id,
        "status": grant.status,
        "mandate_id": grant.mandate_id,
        "mandate_version": str(grant.mandate_version),
        "instrument_token": grant.instrument_token,
        "descriptor": grant.descriptor,
        "mcc": grant.mcc,
        "authorized_amount_cents": str(grant.authorized_amount_cents),
        "currency": grant.currency,
        "expires_at": _iso(grant.expires_at),
        "user_id": grant.user_id or "",
      },
    )
    pipe.expire(key, GRANT_TTL_SECONDS)
    pipe.set(
      INSTRUMENT_KEY.format(token=grant.instrument_token),
      grant.grant_id,
      ex=GRANT_TTL_SECONDS,
    )
    pipe.execute()

  def _grant_from_hash(self, data: dict[str, str]) -> GrantSnapshot | None:
    if not data:
      return None
    return grant_from_dict(data)

  def get_grant(self, grant_id: str) -> GrantSnapshot | None:
    data = self._r.hgetall(GRANT_KEY.format(grant_id=grant_id))
    return self._grant_from_hash(data)

  def get_grant_by_instrument(self, instrument_token: str) -> GrantSnapshot | None:
    gid = self._r.get(INSTRUMENT_KEY.format(token=instrument_token))
    if not gid:
      return None
    return self.get_grant(gid)

  def set_killswitch(self, on: bool) -> None:
    self._r.set(KILLSWITCH_KEY, "1" if on else "0")

  def set_mandate(self, mandate_id: str, *, status: str, version: int) -> None:
    self._r.hset(
      MANDATE_KEY.format(mandate_id=mandate_id),
      mapping={"status": status, "version": str(version)},
    )

  def load_state(self, grant: GrantSnapshot | None) -> AuthorityState:
    kill = self._r.get(KILLSWITCH_KEY) == "1"
    if grant is None:
      return AuthorityState(killswitch_on=kill)
    raw = self._r.hgetall(MANDATE_KEY.format(mandate_id=grant.mandate_id))
    if not raw:
      return AuthorityState(
        killswitch_on=kill,
        mandate_status="active",
        current_mandate_version=grant.mandate_version,
      )
    return AuthorityState(
      killswitch_on=kill,
      mandate_status=str(raw.get("status", "active")),
      current_mandate_version=int(raw.get("version", grant.mandate_version)),
    )

  def get_event(self, event_id: str) -> CachedEvent | None:
    raw = self._r.hgetall(EVENT_KEY.format(event_id=event_id))
    if not raw:
      return None
    d = json.loads(raw["decision"])
    return CachedEvent(
      fingerprint=raw["fingerprint"],
      decision=Decision(
        result=d["result"], reason=d["reason"], rail=d.get("rail", "local_payment_rail_simulator")
      ),
    )

  def commit_decision(
    self,
    *,
    grant_id: str | None,
    event_id: str,
    fingerprint: str,
    decision: Decision,
    consume: bool,
  ) -> tuple[str, Decision]:
    event_key = EVENT_KEY.format(event_id=event_id)
    grant_key = GRANT_KEY.format(grant_id=grant_id or "_none")
    try:
      status, payload = self._script(
        keys=[event_key, grant_key],
        args=[
          fingerprint,
          json.dumps(decision.as_dict(), separators=(",", ":")),
          "1" if consume else "0",
          str(EVENT_TTL_SECONDS),
        ],
      )
    except Exception:
      return "store_error", Decision(result="ERROR", reason="state_store_unavailable")

    if status == "ok":
      return "ok", decision
    if status == "duplicate" and payload:
      d = json.loads(payload)
      return "duplicate", Decision(
        result=d["result"], reason=d["reason"], rail=d.get("rail", "local_payment_rail_simulator")
      )
    if status == "mismatch":
      return "mismatch", Decision(result="ERROR", reason="event_payload_mismatch")
    if status == "lost_race":
      # Re-load grant status for accurate reason.
      if grant_id:
        g = self.get_grant(grant_id)
        if g is None:
          return "lost_race", Decision(result="DECLINED", reason="no_grant")
        if g.status == "CONSUMED":
          return "lost_race", Decision(result="DECLINED", reason="grant_consumed")
        if g.status == "REVOKED":
          return "lost_race", Decision(result="DECLINED", reason="grant_revoked")
      return "lost_race", Decision(result="DECLINED", reason="grant_consumed")
    return "store_error", Decision(result="ERROR", reason="state_store_unavailable")

  def ping(self) -> bool:
    try:
      return bool(self._r.ping())
    except Exception:
      return False
