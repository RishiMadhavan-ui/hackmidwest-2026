"""Transactional authority lifecycle; no model or merchant content can approve."""

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from audit_store import append_event
from authority_errors import AuthorityError
from leash_shared.events import AuditEvent, EventType
from leash_shared.models import (
  AgentRun, AgentRunRegistration, MandateProposal, MandateStatus,
  PurchaseMandate, canonical_json,
)
from principals import Principal
from signing import sign_confirmation, signing_key, verify_confirmation
from payment_operations import cancel_prepared


def utc_now() -> datetime:
  return datetime.now(timezone.utc)


def require_role(principal: Principal, role: str) -> None:
  if principal.role != role:
    raise AuthorityError(403, f"This operation requires the {role} role")


def audit(conn, event_type: EventType, mandate: PurchaseMandate, *, now: datetime, extra=None) -> None:
  event = AuditEvent(type=event_type, at=now, user_id=mandate.user_id, data={
    "mandate_id": mandate.id, "mandate_version": mandate.version,
    "mandate_hash": mandate.canonical_payload_hash,
    "agent_id": mandate.agent_id, "status": mandate.status.value,
    **(extra or {}),
  })
  append_event(conn, event.model_dump(mode="json"))


def transition(conn, mandate: PurchaseMandate, status: MandateStatus, now: datetime) -> None:
  conn.execute("INSERT INTO mandate_transitions (mandate_id, version, status, at) VALUES (%s, %s, %s, %s)",
               (mandate.id, mandate.version, status.value, now))


def scope_head(conn, mandate_id: str, principal: Principal, *, lock=False):
  row = conn.execute(
    "SELECT * FROM mandate_heads WHERE id = %s AND user_id = %s" + (" FOR UPDATE" if lock else ""),
    (mandate_id, principal.user_id),
  ).fetchone()
  if row is None or (principal.role == "agent" and row["agent_id"] != principal.agent_id):
    raise AuthorityError(404, "Mandate not found")
  return row


def version_record(conn, mandate_id: str, version: int, *, now: datetime) -> PurchaseMandate:
  row = conn.execute(
    """SELECT v.record AS draft, v.payload_hash, c.record AS confirmed, c.verify_key,
    (SELECT status FROM mandate_transitions t WHERE t.mandate_id = v.mandate_id
     AND t.version = v.version ORDER BY sequence DESC LIMIT 1) AS status
    FROM mandate_versions v LEFT JOIN mandate_confirmations c
    USING (mandate_id, version) WHERE v.mandate_id = %s AND v.version = %s""",
    (mandate_id, version),
  ).fetchone()
  if row is None:
    raise AuthorityError(404, "Mandate version not found")
  try:
    record = PurchaseMandate.model_validate(row["confirmed"] or row["draft"])
    draft = PurchaseMandate.model_validate(row["draft"])
  except ValidationError as exc:
    raise AuthorityError(503, "Stored mandate failed schema validation") from exc
  if record.canonical_payload_hash != row["payload_hash"] or draft.canonical_payload_hash != row["payload_hash"]:
    raise AuthorityError(503, "Stored mandate content failed integrity verification")
  if row["confirmed"] and not verify_confirmation(record, row["verify_key"]):
    raise AuthorityError(503, "Stored mandate confirmation failed integrity verification")
  status = row["status"]
  if status in {"active", "proposed"} and record.valid_until <= now:
    status = "expired"
  return PurchaseMandate.model_validate({**record.model_dump(), "status": status})


def current_mandate(conn, mandate_id: str, principal: Principal, *, now: datetime, lock=False):
  head = scope_head(conn, mandate_id, principal, lock=lock)
  return version_record(conn, mandate_id, head["current_version"], now=now)


def make_draft(proposal: MandateProposal, *, mandate_id: str, version: int,
               user_id: str, agent_id: str, now: datetime) -> PurchaseMandate:
  start = proposal.valid_from or now
  end = proposal.valid_until or start + timedelta(minutes=30)
  if end <= now:
    raise AuthorityError(422, "Mandate expiry must be in the future")
  return PurchaseMandate.model_validate({
    **proposal.model_dump(), "id": mandate_id, "version": version,
    "user_id": user_id, "agent_id": agent_id, "valid_from": start,
    "valid_until": end, "created_at": now,
  })


def insert_draft(conn, draft: PurchaseMandate, now: datetime) -> None:
  conn.execute("INSERT INTO mandate_versions (mandate_id, version, payload_hash, record) VALUES (%s, %s, %s, %s)",
               (draft.id, draft.version, draft.canonical_payload_hash, Jsonb(draft.model_dump(mode="json"))))
  transition(conn, draft, MandateStatus.PROPOSED, now)
  audit(conn, EventType.MANDATE_PROPOSED, draft, now=now)


def propose(conn, proposal: MandateProposal, principal: Principal, *, now: datetime) -> PurchaseMandate:
  require_role(principal, "agent")
  draft = make_draft(proposal, mandate_id="mnd_" + uuid4().hex, version=1,
                     user_id=principal.user_id, agent_id=principal.agent_id, now=now)
  conn.execute("INSERT INTO mandate_heads (id, user_id, agent_id, current_version) VALUES (%s, %s, %s, 1)",
               (draft.id, draft.user_id, draft.agent_id))
  insert_draft(conn, draft, now)
  return draft


def require_match(mandate: PurchaseMandate, version: int, content_hash: str) -> None:
  if mandate.version != version or mandate.canonical_payload_hash != content_hash:
    raise AuthorityError(409, "Mandate changed; review the current version and hash")


def approve(conn, mandate_id: str, principal: Principal, *, version: int,
            content_hash: str, now: datetime) -> PurchaseMandate:
  require_role(principal, "human")
  from workflow_control import lock_user_authority
  lock_user_authority(conn, principal.user_id)
  draft = current_mandate(conn, mandate_id, principal, now=now, lock=True)
  now = utc_now()  # Waiting for a lock must not extend the approval window.
  require_match(draft, version, content_hash)
  if draft.valid_until <= now:
    raise AuthorityError(409, "Mandate expired before confirmation")
  if draft.status == MandateStatus.ACTIVE:
    return draft  # Identical confirmation retry does not add authority/history.
  if draft.status != MandateStatus.PROPOSED:
    raise AuthorityError(409, "Only a current unexpired draft can be approved")
  key = signing_key()
  # Signing excludes the signature itself, so use an unsigned confirmation view.
  unsigned = draft.model_copy(update={"approved_at": now})
  signature = sign_confirmation(unsigned, key)
  active = PurchaseMandate.model_validate({
    **draft.model_dump(), "approved_at": now, "signature": signature, "status": "active",
  })
  conn.execute("INSERT INTO mandate_confirmations (mandate_id, version, record, verify_key) VALUES (%s, %s, %s, %s)",
               (active.id, active.version, Jsonb(active.model_dump(mode="json")),
                base64.b64encode(bytes(key.verify_key)).decode("ascii")))
  transition(conn, active, MandateStatus.ACTIVE, now)
  audit(conn, EventType.MANDATE_APPROVED, active, now=now)
  return active


def replace(conn, mandate_id: str, principal: Principal, *, version: int,
            content_hash: str, proposal: MandateProposal, now: datetime) -> PurchaseMandate:
  require_role(principal, "human")
  from workflow_control import lock_user_authority
  lock_user_authority(conn, principal.user_id)
  previous = current_mandate(conn, mandate_id, principal, now=now, lock=True)
  now = utc_now()
  require_match(previous, version, content_hash)
  if previous.status not in {MandateStatus.PROPOSED, MandateStatus.ACTIVE} or previous.valid_until <= now:
    raise AuthorityError(409, "Revoked or expired authority requires a new mandate")
  replacement = make_draft(proposal, mandate_id=mandate_id, version=version + 1,
                           user_id=previous.user_id, agent_id=previous.agent_id, now=now)
  transition(conn, previous, MandateStatus.SUPERSEDED, now)
  insert_draft(conn, replacement, now)
  conn.execute("UPDATE mandate_heads SET current_version = %s WHERE id = %s", (replacement.version, mandate_id))
  cancel_prepared(conn, principal.user_id, mandate_id=mandate_id, reason="mandate_replaced")
  audit(conn, EventType.MANDATE_UPDATED, replacement, now=now,
        extra={"superseded_version": version, "superseded_hash": content_hash})
  return replacement


def revoke(conn, mandate_id: str, principal: Principal, *, version: int,
           content_hash: str, now: datetime) -> PurchaseMandate:
  require_role(principal, "human")
  # Same user -> mandate -> operation lock order as payment and replacement.
  # Revocation remains callable after an account stop.
  conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
  mandate = current_mandate(conn, mandate_id, principal, now=now, lock=True)
  now = utc_now()
  require_match(mandate, version, content_hash)
  cancel_prepared(conn, principal.user_id, mandate_id=mandate_id, reason="mandate_revoked")
  if mandate.status == MandateStatus.REVOKED:
    return mandate
  revoked = PurchaseMandate.model_validate({**mandate.model_dump(), "status": "revoked"})
  transition(conn, revoked, MandateStatus.REVOKED, now)
  audit(conn, EventType.MANDATE_REVOKED, revoked, now=now)
  return revoked


def list_mandates(conn, principal: Principal, *, status: MandateStatus | None, now: datetime):
  heads = conn.execute("SELECT id, current_version, agent_id FROM mandate_heads WHERE user_id = %s ORDER BY id",
                       (principal.user_id,)).fetchall()
  items = []
  for head in heads:
    if principal.role == "agent" and head["agent_id"] != principal.agent_id:
      continue
    mandate = version_record(conn, head["id"], head["current_version"], now=now)
    if status is not None and mandate.status != status:
      continue
    if status == MandateStatus.ACTIVE and mandate.valid_from > now:
      continue
    items.append(mandate)
  return items


def register_run(conn, registration: AgentRunRegistration, principal: Principal, *, now: datetime) -> AgentRun:
  require_role(principal, "agent")
  from workflow_control import lock_user_authority
  lock_user_authority(conn, principal.user_id)
  if registration.agent_mode not in principal.allowed_modes:
    raise AuthorityError(403, "Agent mode is not authorized for this credential")
  # Serializes with replacement/revocation; retries retain the original binding.
  mandate = current_mandate(conn, registration.mandate_id, principal, now=now, lock=True)
  now = utc_now()
  existing = conn.execute("SELECT * FROM agent_runs WHERE id = %s", (registration.id,)).fetchone()
  if existing is not None:
    if existing["user_id"] != principal.user_id or existing["agent_id"] != principal.agent_id:
      raise AuthorityError(409, "Run identity is already registered")
    if conn.execute("SELECT run_id FROM run_cancellations WHERE run_id=%s", (registration.id,)).fetchone():
      raise AuthorityError(409, "Stopped run cannot be registered again")
    if canonical_json(existing["registration"]) != canonical_json(registration):
      raise AuthorityError(409, "Run registration conflicts with its original content")
    original = AgentRun.model_validate(existing["record"])
    if (mandate.status != MandateStatus.ACTIVE or not mandate.valid_from <= now < mandate.valid_until or
        original.mandate_version != mandate.version or original.mandate_hash != mandate.canonical_payload_hash):
      raise AuthorityError(409, "Registered run authority is no longer current")
    return original
  if mandate.status != MandateStatus.ACTIVE or not mandate.valid_from <= now < mandate.valid_until:
    raise AuthorityError(409, "Run requires a current confirmed mandate within its validity window")
  # Distinct mandate locks do not serialize a shared run ID; lock that ID too.
  conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (registration.id,))
  if conn.execute("SELECT id FROM agent_runs WHERE id = %s", (registration.id,)).fetchone():
    raise AuthorityError(409, "Run identity is already registered; retry the original registration")
  run = AgentRun(
    **registration.model_dump(), user_id=principal.user_id, agent_id=principal.agent_id,
    mandate_version=mandate.version, mandate_hash=mandate.canonical_payload_hash,
    status="running", created_at=now, started_at=now,
  )
  conn.execute("INSERT INTO agent_runs (id, user_id, agent_id, mandate_id, mandate_version, registration, record) VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (run.id, run.user_id, run.agent_id, run.mandate_id, run.mandate_version,
                Jsonb(registration.model_dump(mode="json")), Jsonb(run.model_dump(mode="json"))))
  audit(conn, EventType.AGENT_RUN_STARTED, mandate, now=now,
        extra={"run_id": run.id, "agent_mode": run.agent_mode})
  return run
