"""Verified local-rail activation with stable identities and outcome reconciliation.

The immutable preflight ledger remains intact. Live Lithic is not enabled here.
"""

import hashlib
import os
from datetime import datetime, timedelta

import httpx
from fastapi import Depends, Request
from psycopg.types.json import Jsonb

from authority_errors import AuthorityError
from db import get_conn
from execution import enabled, locked, rail, validate_scope, TLS_CONTEXT
from leash_shared.models import AuthorizationGrant, CheckoutSnapshot, PaymentResponse, canonical_json
from merchant_execution import merchant_auth, router, checkout_projection
from payment_operations import prepare, finish, event, persist_observation
from payment_service import (_lock_payment_authority, _map_checkout, _confirmation_valid,
  _successful_purchases, _persist, _original_response)
from checkout_verifier import verify_checkout
from mandate_service import utc_now


def move(conn, op, state, reason):
  updated = conn.execute("""UPDATE payment_operations SET state=%s,revision=revision+1,
    reason=%s,updated_at=now() WHERE id=%s AND revision=%s RETURNING *""",
    (state, reason, op["id"], op["revision"])).fetchone()
  if not updated:
    raise AuthorityError(409, "Operation changed")
  event(conn, updated, state, reason=reason)
  return updated


def activation(conn, payment_id):
  return conn.execute("SELECT * FROM payment_activations WHERE payment_id=%s", (payment_id,)).fetchone()


def response_for(conn, op):
  a = activation(conn, op["id"])
  if not a:
    return _original_response(conn, op)
  g = a["grant_record"]
  state = op["state"]
  return PaymentResponse(id=op["id"], status="used" if state == "authorized" else
    "approved" if state == "ready" else "denied" if state in {"declined","cancelled"} else "pending_guardian",
    verification_id=g["verification_id"], grant_id=g["grant_id"],
    reasons=() if state in {"ready","authorized"} else (op["reason"] or state,),
    payment_result="APPROVED" if state == "authorized" else "DECLINED" if state == "declined" else None)


def _merchant_facts(checkout_id):
  from urllib.parse import quote
  from payment_service import _require_integrations, _store_url
  _require_integrations()
  token = os.getenv("MERCHANT_BACKEND_TOKEN", "")
  if len(token) < 32:
    raise AuthorityError(503, "Merchant backend credential is not configured")
  try:
    with httpx.Client(timeout=4, follow_redirects=False, verify=TLS_CONTEXT) as client:
      res = client.get(_store_url() + "/api/checkouts/" + quote(checkout_id, safe=""),
        headers={"Authorization": "Bearer " + token})
    if not res.is_success:
      raise AuthorityError(502, "Canonical merchant checkout is unavailable")
    body = res.json()
    if not isinstance(body, dict):
      raise ValueError()
    return body
  except (httpx.HTTPError, ValueError):
    raise AuthorityError(502, "Canonical merchant checkout is unavailable") from None


def request_verified(conn, body, principal, headers):
  enabled()
  run, lease = validate_scope(conn, headers, "mcp-leash", "request_payment", principal=principal)
  if body.run_id != run["id"] or body.mandate_id != run["mandate_id"]:
    raise AuthorityError(403, "Payment scope mismatch")
  mandate = _lock_payment_authority(conn, body, principal)
  op = prepare(conn, body, principal, mandate)
  if op["state"] != "prepared":
    return response_for(conn, op)
  conn.commit()  # Stable IDs exist before merchant I/O or activation.
  try:
    facts = _merchant_facts(body.checkout_id)
  except AuthorityError as error:
    conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
    op = conn.execute("SELECT * FROM payment_operations WHERE id=%s FOR UPDATE", (op["id"],)).fetchone()
    if op["state"] == "prepared":
      finish(conn, op, "blocked", "checkout_source_unavailable", error=error)
      conn.commit()
    raise
  run, lease = validate_scope(conn, headers, "mcp-leash", "request_payment", principal=principal)
  mandate = _lock_payment_authority(conn, body, principal)
  op = conn.execute("SELECT * FROM payment_operations WHERE id=%s FOR UPDATE", (op["id"],)).fetchone()
  if op["state"] != "prepared":
    return response_for(conn, op)
  owned = conn.execute("SELECT * FROM merchant_checkouts WHERE checkout_id=%s", (body.checkout_id,)).fetchone()
  if (not owned or owned["user_id"] != principal.user_id or owned["run_id"] != run["id"]
      or owned["generation"] != lease["generation"] or checkout_projection(owned) != facts
      or owned["expires_at"] <= utc_now()):
    error = AuthorityError(409, "Checkout ownership, frozen revision or expiry failed")
    finish(conn, op, "blocked", "checkout_source_unavailable_or_wrong_owner", error=error)
    conn.commit()
    raise error
  observed = _map_checkout(facts, user_id=principal.user_id, payment_id=op["id"], now=utc_now())
  normalized = observed.model_dump(mode="json")
  normalized.update(revision=owned["revision"], session_id=owned["session_id"],
                    expires_at=owned["expires_at"].isoformat(), checkout_hash=None)
  checkout = CheckoutSnapshot.model_validate(normalized)
  verified = verify_checkout(mandate, checkout, now=utc_now(),
    confirmation_valid=_confirmation_valid(conn, mandate), checkout_authenticated=True,
    successful_purchases=_successful_purchases(conn, principal.user_id, mandate))
  persist_observation(conn, op, checkout, facts, financial_authority=verified.decision.value == "VERIFIED")
  if verified.decision.value != "VERIFIED":
    result = PaymentResponse(id=op["id"], status="blocked", reasons=verified.reasons, verification_id=verified.id)
    _persist(conn, payment_id=op["id"], principal=principal, mandate=mandate,
      checkout_id=body.checkout_id, run_id=run["id"], status="blocked", verification=verified,
      grant=None, instrument_token=None, checkout_hash=checkout.checkout_hash, response=result)
    finish(conn, op, "blocked", "deterministic_policy_block")
    return result
  now = utc_now()
  grant = AuthorizationGrant(grant_id=op["grant_reference"], payment_id=op["id"],
    mandate_id=mandate.id, mandate_version=mandate.version, mandate_hash=mandate.canonical_payload_hash,
    user_id=principal.user_id, verification_id=verified.id, verified_checkout_id=checkout.checkout_id,
    verified_checkout_hash=checkout.checkout_hash, payment_instrument_id=str(op["instrument_reference"]),
    merchant_id=checkout.merchant_id, merchant_descriptor=checkout.merchant.descriptor,
    mcc=checkout.merchant.mcc, authorized_amount_cents=checkout.total_cents, currency=checkout.currency,
    merchant_binding_id="bind_" + op["id"], bound_at=now, issued_at=now,
    expires_at=min(checkout.expires_at, mandate.valid_until, lease["deadline"], now+timedelta(minutes=2)),
    mandate_expires_at=mandate.valid_until, checkout_expires_at=checkout.expires_at)
  conn.execute("""INSERT INTO payment_activations(payment_id,run_id,generation,rail_epoch,
    grant_record,verification,checkout_snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
    (op["id"], run["id"], lease["generation"], lease["rail_epoch"], Jsonb(grant.model_dump(mode="json")),
     Jsonb(verified.model_dump(mode="json")), Jsonb(checkout.model_dump(mode="json"))))
  op = move(conn, op, "activating", "verified_checkout_bound")
  conn.commit()  # Grant and exact merchant binding are immutable before install.
  try:
    result = rail("PUT", "/internal/execution/grants", {"grant": grant.model_dump(mode="json"),
      "run_id": run["id"], "generation": lease["generation"], "epoch": lease["rail_epoch"],
      "authorization_event_id": str(op["authorization_event_id"])})
    accepted = result.get("grant_id") == grant.grant_id and result.get("epoch") == lease["rail_epoch"]
  except AuthorityError:
    accepted = False
  conn.execute("SELECT id FROM leash_users WHERE id=%s FOR UPDATE", (principal.user_id,))
  op = conn.execute("SELECT * FROM payment_operations WHERE id=%s FOR UPDATE", (op["id"],)).fetchone()
  if op["state"] == "activating":
    try:
      locked(conn, run["id"], principal)
    except AuthorityError:
      accepted = False
    op = move(conn, op, "ready" if accepted else "reconciling", "grant_installed" if accepted else "activation_outcome_unknown")
  return response_for(conn, op)


def authorization_payload(op, a):
  g = a["grant_record"]
  return {"event_id": str(op["authorization_event_id"]), "request_type": "AUTHORIZATION",
    "instrument_token": g["payment_instrument_id"], "descriptor": g["merchant_descriptor"],
    "mcc": g["mcc"], "amount_cents": g["authorized_amount_cents"], "currency": g["currency"],
    "checkout_id": g["verified_checkout_id"], "checkout_hash": g["verified_checkout_hash"],
    "merchant_binding_id": g["merchant_binding_id"]}


def reconcile(conn, op):
  a = activation(conn, op["id"])
  if not a or op["state"] in {"authorized","declined","cancelled"}:
    return op
  result = rail("GET", "/internal/execution/events/" + str(op["authorization_event_id"]))
  if result.get("epoch") != a["rail_epoch"]:
    if op["state"] != "reconciling":
      op = move(conn, op, "reconciling", "rail_epoch_changed")
    return op
  payload = {**authorization_payload(op, a), "event_scope": "local"}
  expected = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
  if result.get("found") and result.get("fingerprint") == expected:
    decision = result.get("decision", {})
    if decision.get("result") in {"APPROVED","DECLINED"} and decision.get("rail") == "local_payment_rail_simulator":
      conn.execute("INSERT INTO payment_outcomes(payment_id,event_id,record) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        (op["id"], str(op["authorization_event_id"]), Jsonb(decision)))
      if op["state"] in {"ready","activating"}:
        op = move(conn, op, "reconciling", "observed_rail_outcome")
      op = move(conn, op, "authorized" if decision["result"] == "APPROVED" else "declined", decision["reason"])
  elif result.get("found") is False:
    scope = conn.execute("SELECT rail_stopped_at FROM run_executions WHERE run_id=%s", (op["run_id"],)).fetchone()
    if scope and scope["rail_stopped_at"]:
      if op["state"] == "authorizing":
        op = move(conn, op, "reconciling", "stopped_awaiting_reconciliation")
      op = move(conn, op, "cancelled", "rail_barrier_confirmed_without_authorization")
  return op


@router.post("/checkouts/{checkout_id}/begin", dependencies=[Depends(merchant_auth)])
def begin_complete(checkout_id: str, body: dict, request: Request):
  with get_conn() as conn:
    run, lease = validate_scope(conn, request.headers, "mcp-store", "complete_checkout")
    op = conn.execute("SELECT * FROM payment_operations WHERE id=%s AND checkout_id=%s AND run_id=%s FOR UPDATE",
      (body.get("payment_id"), checkout_id, run["id"])).fetchone()
    if not op or op["state"] not in {"ready","authorizing"}:
      raise AuthorityError(409, "Exact verified payment is not ready for completion")
    a = activation(conn, op["id"])
    if not a or a["generation"] != lease["generation"] or a["rail_epoch"] != lease["rail_epoch"]:
      raise AuthorityError(409, "Payment scope changed")
    if datetime.fromisoformat(a["grant_record"]["expires_at"].replace("Z", "+00:00")) <= utc_now():
      raise AuthorityError(409, "Payment grant expired")
    if op["state"] == "ready":
      op = move(conn, op, "authorizing", "merchant_completion_started")
    return authorization_payload(op, a)


@router.post("/checkouts/{checkout_id}/reconcile", dependencies=[Depends(merchant_auth)])
def complete_result(checkout_id: str, body: dict, request: Request):
  with get_conn() as conn:
    run, _ = validate_scope(conn, request.headers, "mcp-store", "complete_checkout", live=False)
    op = conn.execute("SELECT * FROM payment_operations WHERE id=%s AND checkout_id=%s AND run_id=%s FOR UPDATE",
      (body.get("payment_id"), checkout_id, run["id"])).fetchone()
    if not op:
      raise AuthorityError(404, "Payment not found")
    op = reconcile(conn, op)
    return {"checkout_id": checkout_id, "payment_id": op["id"], "status": op["state"],
      "rail": "local_payment_rail_simulator"}
