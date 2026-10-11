"""Trusted checkout retrieval, verify, grant seed, and store bind (R03/R04)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb

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
  GrantStatus,
  Merchant,
  PaymentProposal,
  PaymentResponse,
  ProductAttribute,
  PurchaseMandate,
  VerificationDecision,
)
from mandate_service import current_mandate, utc_now
from principals import Principal
from signing import verify_confirmation


MERCHANT_ID = "mer_volt_supply"
GRANT_TTL = timedelta(minutes=15)
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
  if not _webhook_url() or len(_webhook_internal_token()) < 32:
    raise AuthorityError(503, "Rail WEBHOOK_URL/WEBHOOK_INTERNAL_TOKEN is not configured")


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
  if res.status_code >= 400:
    raise AuthorityError(502, "Trusted merchant rejected checkout retrieval")
  data = res.json()
  if not isinstance(data, dict) or not data.get("checkout_id"):
    raise AuthorityError(502, "Trusted merchant returned an invalid checkout")
  return data


def _map_checkout(
  store: dict[str, Any],
  *,
  user_id: str,
  payment_id: str,
  now: datetime,
) -> CheckoutSnapshot:
  lines = store.get("line_items") or []
  if not isinstance(lines, list) or not lines:
    raise AuthorityError(502, "Trusted checkout missing line items")
  items = []
  for line in lines:
    if not isinstance(line, dict):
      raise AuthorityError(502, "Trusted checkout has invalid line items")
    attrs = []
    for raw in line.get("attributes") or []:
      if isinstance(raw, dict) and "name" in raw and "value" in raw:
        attrs.append(ProductAttribute(name=str(raw["name"]), value=raw["value"]))
    items.append(
      CheckoutItem(
        sku=str(line.get("sku") or line.get("product_id") or ""),
        product_name=str(line.get("name") or ""),
        product_category=line.get("category"),
        quantity=int(line.get("quantity") or 1),
        unit_cents=int(line.get("price_cents") or 0),
        recurring=bool(line.get("recurring")),
        subscription=bool(line.get("subscription")),
        billing_interval=line.get("billing_interval"),
        attributes=tuple(attrs),
      )
    )
  total = int(store["total_cents"])
  descriptor = str(store.get("merchant_descriptor") or "VOLT SUPPLY CO")
  mcc = str(store.get("mcc") or "5732")
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


def _successful_purchases(conn, user_id: str) -> int:
  row = conn.execute(
    """SELECT COUNT(*)::int AS n FROM payment_attempts
       WHERE user_id=%s AND status IN ('approved','used')""",
    (user_id,),
  ).fetchone()
  return int(row["n"] if row else 0)


def _resolve_instrument(conn, user_id: str) -> tuple[str, str | None]:
  """Return (instrument_token, last4). Local demo instrument when no Lithic card."""
  # Prefer linked auth user card tokens.
  row = conn.execute(
    """SELECT u.lithic_card_token AS token, u.lithic_card_last_four AS last4
       FROM leash_users l JOIN users u ON u.id = l.auth_user_id
       WHERE l.id=%s AND u.lithic_card_token IS NOT NULL""",
    (user_id,),
  ).fetchone()
  if row and row["token"]:
    last4 = str(row["last4"]) if row["last4"] else None
    return str(row["token"]), last4
  card = conn.execute(
    """SELECT card_token, last_four FROM lithic_cards
       WHERE user_id = (SELECT auth_user_id FROM leash_users WHERE id=%s)
       ORDER BY created_at DESC NULLS LAST LIMIT 1""",
    (user_id,),
  ).fetchone()
  if card and card["card_token"]:
    last4 = str(card["last_four"]) if card.get("last_four") else None
    return str(card["card_token"]), last4
  # Labeled local-rail instrument — not a network PAN.
  return f"ins_local_{user_id.removeprefix('usr_')[:32]}", None


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
  _require_integrations()
  now = utc_now()
  mandate = current_mandate(conn, body.mandate_id, principal, now=now)
  if mandate.status.value != "active":
    raise AuthorityError(409, "Mandate is not active")

  # Idempotent replay: same agent + mandate + checkout with an existing row.
  prior = conn.execute(
    """SELECT id, record FROM payment_attempts
       WHERE user_id=%s AND agent_id=%s AND mandate_id=%s AND checkout_id=%s
       ORDER BY created_at DESC LIMIT 1""",
    (principal.user_id, principal.agent_id, body.mandate_id, body.checkout_id),
  ).fetchone()
  if prior and prior["record"]:
    return PaymentResponse.model_validate(prior["record"])

  payment_id = "pay_" + uuid4().hex
  store = _fetch_store_checkout(body.checkout_id)
  checkout = _map_checkout(store, user_id=principal.user_id, payment_id=payment_id, now=now)
  confirmation_valid = _confirmation_valid(conn, mandate)
  verification = verify_checkout(
    mandate,
    checkout,
    now=now,
    confirmation_valid=confirmation_valid,
    checkout_authenticated=True,
    successful_purchases=_successful_purchases(conn, principal.user_id),
  )

  if verification.decision != VerificationDecision.VERIFIED:
    response = PaymentResponse(
      id=payment_id,
      status="blocked",
      reasons=verification.reasons,
      verification_id=verification.id,
    )
    _persist(
      conn,
      payment_id=payment_id,
      principal=principal,
      mandate=mandate,
      checkout_id=body.checkout_id,
      run_id=body.run_id,
      status="blocked",
      verification=verification,
      grant=None,
      instrument_token=None,
      checkout_hash=checkout.checkout_hash,
      response=response,
    )
    return response

  instrument, last4 = _resolve_instrument(conn, principal.user_id)
  issued_at = now
  bound_at = now
  expires_at = now + GRANT_TTL
  grant = AuthorizationGrant(
    grant_id="grt_" + uuid4().hex,
    payment_id=payment_id,
    mandate_id=mandate.id,
    mandate_version=mandate.version,
    mandate_hash=mandate.canonical_payload_hash,
    user_id=principal.user_id,
    verification_id=verification.id,
    verified_checkout_id=checkout.checkout_id,
    verified_checkout_hash=checkout.checkout_hash,
    payment_instrument_id=instrument,
    merchant_id=MERCHANT_ID,
    merchant_descriptor=checkout.merchant.descriptor,
    mcc=checkout.merchant.mcc,
    authorized_amount_cents=checkout.total_cents,
    currency="USD",
    merchant_binding_id=f"bind_{checkout.checkout_id}",
    bound_at=bound_at,
    issued_at=issued_at,
    expires_at=expires_at,
    mandate_expires_at=mandate.valid_until,
    checkout_expires_at=checkout.expires_at,
    status=GrantStatus.ISSUED,
  )

  # Side effects only after verification succeeded.
  _seed_grant(grant)
  _bind_store(checkout_id=checkout.checkout_id, payment_id=payment_id, grant=grant)

  response = PaymentResponse(
    id=payment_id,
    status="approved",
    reasons=(),
    verification_id=verification.id,
    grant_id=grant.grant_id,
  )
  # Optional metadata for complete_checkout (not part of PaymentResponse schema).
  # Callers that need the instrument read it from GET extensions via record dump —
  # expose via a thin envelope in the route layer.
  _persist(
    conn,
    payment_id=payment_id,
    principal=principal,
    mandate=mandate,
    checkout_id=body.checkout_id,
    run_id=body.run_id,
    status="approved",
    verification=verification,
    grant=grant,
    instrument_token=instrument,
    checkout_hash=checkout.checkout_hash,
    response=response,
  )
  # Stash instrument for the HTTP layer without violating PaymentResponse.
  response._instrument_token = instrument  # type: ignore[attr-defined]
  response._card_last4 = last4  # type: ignore[attr-defined]
  return response


def get_payment(conn, payment_id: str, principal: Principal) -> dict[str, Any]:
  row = conn.execute(
    """SELECT record, instrument_token, status, grant_id, verification_id
       FROM payment_attempts WHERE id=%s AND user_id=%s""",
    (payment_id, principal.user_id),
  ).fetchone()
  if row is None:
    raise AuthorityError(404, "Payment not found")
  payload = dict(row["record"] or {})
  # Never re-emit full PAN; instrument token is enough for bound complete.
  if row["instrument_token"]:
    payload["instrument_token"] = row["instrument_token"]
  return payload
