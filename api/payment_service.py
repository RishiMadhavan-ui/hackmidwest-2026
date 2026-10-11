"""Trusted checkout preflight. Spending stays closed until durable controls exist."""

from __future__ import annotations

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from audit_store import append_event
from authority_errors import AuthorityError
from checkout_verifier import verify_checkout
from leash_shared.events import AuditEvent, EventType
from leash_shared.models import (
  AuthorizationGrant,
  CheckoutItem,
  CheckoutSnapshot,
  CheckoutSource,
  CheckoutVerification,
  Merchant,
  PaymentProposal,
  PaymentResponse,
  ProductAttribute,
  PurchaseMandate,
  VerificationDecision,
  canonical_json,
)
from mandate_service import current_mandate, require_role, utc_now
from principals import Principal
from signing import verify_confirmation
from workflow_control import lock_user_authority


MERCHANT_ID = "mer_volt_supply"
CHECKOUT_TTL = timedelta(minutes=30)


def _store_url() -> str:
  return os.getenv("STORE_URL", "").strip().rstrip("/")


def _store_token() -> str:
  return os.getenv("STORE_API_TOKEN", "").strip()


def _webhook_url() -> str:
  return os.getenv("WEBHOOK_URL", "").strip().rstrip("/")


def _webhook_internal_token() -> str:
  return os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()


def _require_integrations() -> None:
  if not _store_url() or len(_store_token()) < 32:
    raise AuthorityError(503, "Trusted merchant STORE_URL/STORE_API_TOKEN is not configured")


def _fetch_store_checkout(checkout_id: str) -> dict[str, Any]:
  try:
    with httpx.Client(timeout=5.0) as client:
      res = client.get(
        f"{_store_url()}/api/checkouts/{checkout_id}",
        headers={
          "Authorization": f"Bearer {_store_token()}",
          "Accept": "application/json",
        },
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Trusted merchant unreachable") from exc
  if res.status_code == 404:
    raise AuthorityError(404, "Checkout not found at trusted merchant")
  if not res.is_success:
    raise AuthorityError(502, "Trusted merchant rejected checkout retrieval")
  try:
    data = res.json()
  except ValueError:
    raise AuthorityError(502, "Trusted merchant returned invalid JSON") from None
  if not isinstance(data, dict) or data.get("checkout_id") != checkout_id:
    raise AuthorityError(502, "Trusted merchant returned an invalid checkout")
  return data


def _map_checkout(
  store: dict[str, Any],
  *,
  user_id: str,
  payment_id: str,
  now: datetime,
) -> CheckoutSnapshot:
  try:
    return _map_checkout_facts(store, user_id=user_id, payment_id=payment_id, now=now)
  except (ValidationError, KeyError, TypeError, ValueError):
    raise AuthorityError(502, "Trusted checkout facts failed validation") from None


def _map_checkout_facts(store, *, user_id, payment_id, now):
  # This connector has no durable owner/session/expiry proof yet. These are
  # preflight observations, never sufficient to issue spending authority.
  if store.get("status") != "open" or store.get("currency") != "USD":
    raise ValueError("Invalid checkout state or currency")
  lines = store["line_items"]
  if not isinstance(lines, list) or not lines:
    raise AuthorityError(502, "Trusted checkout missing line items")
  items = []
  for line in lines:
    if not isinstance(line, dict):
      raise AuthorityError(502, "Trusted checkout has invalid line items")
    if type(line["recurring"]) is not bool or type(line["subscription"]) is not bool:
      raise ValueError("Explicit recurrence facts required")
    attrs = [ProductAttribute.model_validate(raw) for raw in line["attributes"]]
    items.append(
      CheckoutItem(
        sku=line["sku"],
        product_name=line["name"],
        product_category=line["category"],
        quantity=line["quantity"],
        unit_cents=line["price_cents"],
        recurring=line["recurring"],
        subscription=line["subscription"],
        billing_interval=line["billing_interval"],
        attributes=tuple(attrs),
      )
    )
  total = store["total_cents"]
  descriptor = store["merchant_descriptor"]
  mcc = store["mcc"]
  if type(store["recurring"]) is not bool or store["recurring"] != any(item.recurring for item in items):
    raise ValueError("Inconsistent recurrence")
  facts = {key: store[key] for key in (
    "checkout_id", "currency", "line_items", "mcc", "merchant_descriptor", "recurring", "total_cents"
  )}
  if hashlib.sha256(canonical_json(facts).encode("utf-8")).hexdigest() != store["facts_hash"]:
    raise ValueError("Checkout facts hash mismatch")
  retrieved = now
  expires = now + CHECKOUT_TTL
  return CheckoutSnapshot(
    checkout_id=str(store["checkout_id"]),
    revision=1,
    purchase_attempt_id=payment_id,
    user_id=user_id,
    merchant_id=MERCHANT_ID,
    session_id=f"ses_{store['checkout_id']}",
    merchant=Merchant(
      name="Volt Supply Co.",
      descriptor=descriptor,
      mcc=mcc,
      url=_store_url() or "http://store:8000",
    ),
    items=tuple(items),
    currency="USD",
    subtotal_cents=total,
    tax_cents=0,
    shipping_cents=0,
    total_cents=total,
    expires_at=expires,
    source=CheckoutSource(
      source_id=f"src_{store['checkout_id']}",
      url=f"{_store_url()}/api/checkouts/{store['checkout_id']}",
      retrieved_at=retrieved,
      method="server_fetch",
    ),
  )


def _confirmation_valid(conn, mandate: PurchaseMandate) -> bool:
  row = conn.execute(
    "SELECT verify_key FROM mandate_confirmations WHERE mandate_id=%s AND version=%s",
    (mandate.id, mandate.version),
  ).fetchone()
  if row is None or not mandate.signature:
    return False
  return verify_confirmation(mandate, row["verify_key"])


def _successful_purchases(conn, user_id: str, mandate: PurchaseMandate) -> int:
  row = conn.execute(
    """SELECT COUNT(*)::int AS n FROM payment_attempts
       WHERE user_id=%s AND mandate_id=%s AND mandate_version=%s
       AND status IN ('approved','used')""",
    (user_id, mandate.id, mandate.version),
  ).fetchone()
  return int(row["n"] if row else 0)


def _seed_grant(grant: AuthorizationGrant) -> None:
  try:
    with httpx.Client(timeout=5.0) as client:
      res = client.put(
        f"{_webhook_url()}/internal/grants",
        headers={
          "Authorization": f"Bearer {_webhook_internal_token()}",
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        json=grant.model_dump(mode="json"),
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Payment rail unreachable while seeding grant") from exc
  if res.status_code >= 400:
    raise AuthorityError(502, "Payment rail rejected grant install")


def _bind_store(
  *,
  checkout_id: str,
  payment_id: str,
  grant: AuthorizationGrant,
) -> None:
  body = {
    "payment_id": payment_id,
    "grant_id": grant.grant_id,
    "instrument_token": grant.payment_instrument_id,
    "merchant_binding_id": grant.merchant_binding_id,
    "checkout_hash": grant.verified_checkout_hash,
    "authorized_amount_cents": grant.authorized_amount_cents,
    "expires_at": grant.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
  }
  try:
    with httpx.Client(timeout=5.0) as client:
      res = client.post(
        f"{_store_url()}/api/checkouts/{checkout_id}/bind",
        headers={
          "Authorization": f"Bearer {_store_token()}",
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        json=body,
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Trusted merchant unreachable while binding checkout") from exc
  if res.status_code >= 400:
    raise AuthorityError(502, "Trusted merchant rejected checkout binding")


def _persist(
  conn,
  *,
  payment_id: str,
  principal: Principal,
  mandate: PurchaseMandate,
  checkout_id: str,
  run_id: str | None,
  status: str,
  verification: CheckoutVerification | None,
  grant: AuthorizationGrant | None,
  instrument_token: str | None,
  checkout_hash: str | None,
  response: PaymentResponse,
) -> None:
  conn.execute(
    """INSERT INTO payment_attempts (
         id, user_id, agent_id, mandate_id, mandate_version, checkout_id, run_id,
         status, verification_id, grant_id, instrument_token, checkout_hash,
         verification, record
       ) VALUES (
         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
       )
       ON CONFLICT (id) DO UPDATE SET
         status=EXCLUDED.status,
         verification_id=EXCLUDED.verification_id,
         grant_id=EXCLUDED.grant_id,
         instrument_token=EXCLUDED.instrument_token,
         checkout_hash=EXCLUDED.checkout_hash,
         verification=EXCLUDED.verification,
         record=EXCLUDED.record,
         updated_at=now()""",
    (
      payment_id,
      principal.user_id,
      principal.agent_id,
      mandate.id,
      mandate.version,
      checkout_id,
      run_id,
      status,
      verification.id if verification else None,
      grant.grant_id if grant else None,
      instrument_token,
      checkout_hash,
      Jsonb(verification.model_dump(mode="json")) if verification else None,
      Jsonb(response.model_dump(mode="json")),
    ),
  )
  event_type = (
    EventType.PAYMENT_APPROVED if status == "approved" else EventType.PAYMENT_DENIED
  )
  append_event(
    conn,
    AuditEvent(
      type=event_type,
      at=utc_now(),
      user_id=principal.user_id,
      data={
        "payment_id": payment_id,
        "mandate_id": mandate.id,
        "checkout_id": checkout_id,
        "status": status,
        "grant_id": grant.grant_id if grant else None,
        "verification_id": verification.id if verification else None,
        "reasons": list(response.reasons),
      },
    ).model_dump(mode="json"),
  )


def request_payment(conn, body: PaymentProposal, principal: Principal) -> PaymentResponse:
  require_role(principal, "agent")
  lock_user_authority(conn, principal.user_id)
  if body.run_id is None:
    raise AuthorityError(422, "A registered run_id is required")
  run = conn.execute(
    """SELECT id FROM agent_runs WHERE id=%s AND user_id=%s
    AND agent_id=%s AND mandate_id=%s""",
    (body.run_id, principal.user_id, principal.agent_id, body.mandate_id),
  ).fetchone()
  if run is None:
    raise AuthorityError(404, "Registered run not found")
  if conn.execute("SELECT run_id FROM run_cancellations WHERE run_id=%s", (body.run_id,)).fetchone():
    raise AuthorityError(409, "Run has been stopped")
  _require_integrations()
  now = utc_now()
  mandate = current_mandate(conn, body.mandate_id, principal, now=now)
  if mandate.status.value != "active":
    raise AuthorityError(409, "Mandate is not active")

  # User lock serializes same-scope preflights with stop and duplicate requests.
  prior = conn.execute(
    """SELECT id, record FROM payment_attempts
       WHERE user_id=%s AND agent_id=%s AND mandate_id=%s AND mandate_version=%s
       AND checkout_id=%s AND run_id=%s
       ORDER BY created_at DESC LIMIT 1""",
    (principal.user_id, principal.agent_id, body.mandate_id, mandate.version, body.checkout_id, body.run_id),
  ).fetchone()
  if prior and prior["record"]:
    previous = PaymentResponse.model_validate(prior["record"])
    if previous.status == "approved":
      # Historical grant approval is not proof of an authorized transaction.
      raise AuthorityError(409, "Historical grant requires reconciliation; no new purchase is authorized")
    return previous

  payment_id = "pay_" + uuid4().hex
  store = _fetch_store_checkout(body.checkout_id)
  if store.get("checkout_id") != body.checkout_id:
    raise AuthorityError(502, "Trusted merchant returned a different checkout")
  checkout = _map_checkout(store, user_id=principal.user_id, payment_id=payment_id, now=now)
  confirmation_valid = _confirmation_valid(conn, mandate)
  verification = verify_checkout(
    mandate,
    checkout,
    now=now,
    confirmation_valid=confirmation_valid,
    checkout_authenticated=True,
    successful_purchases=_successful_purchases(conn, principal.user_id, mandate),
  )

  # The incoming grant path wrote to the rail/store before committing SQL,
  # lacked run financial revocation, and reused account instruments. Preserve
  # retrieval/verification, but never install a usable grant until the durable
  # operation/reconciliation and atomic run barriers are implemented and tested.
  reasons = verification.reasons if verification.decision != VerificationDecision.VERIFIED else (
    "financial_authority_unavailable",
  )
  response = PaymentResponse(
    id=payment_id, status="blocked", reasons=reasons, verification_id=verification.id,
  )
  _persist(
    conn, payment_id=payment_id, principal=principal, mandate=mandate,
    checkout_id=body.checkout_id, run_id=body.run_id, status="blocked",
    verification=verification, grant=None, instrument_token=None,
    checkout_hash=checkout.checkout_hash, response=response,
  )
  return response


def get_payment(conn, payment_id: str, principal: Principal) -> dict[str, Any]:
  require_role(principal, "agent")
  row = conn.execute(
    """SELECT record, instrument_token, status, grant_id, verification_id
       FROM payment_attempts WHERE id=%s AND user_id=%s AND agent_id=%s""",
    (payment_id, principal.user_id, principal.agent_id),
  ).fetchone()
  if row is None:
    raise AuthorityError(404, "Payment not found")
  payload = dict(row["record"] or {})
  # An old grant record is history, not new usable authority or a paid receipt.
  payload["authorization_status"] = "unverified"
  payload["payment_execution"] = "unavailable"
  return payload
