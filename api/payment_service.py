"""Trusted checkout preflight with local-rail grant activation and store bind."""

from __future__ import annotations

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from urllib.parse import quote, urlsplit

import httpx
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from audit_store import append_event
from authority_errors import AuthorityError
from checkout_verifier import verify_checkout
from leash_shared.events import AuditEvent, EventType, sanitize_event_data
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
  canonical_json,
)
from mandate_service import current_mandate, require_role, utc_now
from principals import Principal
from signing import verify_confirmation
from workflow_control import lock_user_authority
from payment_operations import prepare, finish, persist_observation, cancel_prepared


MERCHANT_ID = "mer_volt_supply"
CHECKOUT_TTL = timedelta(minutes=30)


def _store_url() -> str:
  return os.getenv("STORE_URL", "").strip().rstrip("/")


def _store_token() -> str:
  return os.getenv("STORE_API_TOKEN", "").strip()


def _store_charge_token() -> str:
  return os.getenv("STORE_CHARGE_TOKEN", "").strip()


def _webhook_url() -> str:
  return os.getenv("WEBHOOK_URL", "").strip().rstrip("/")


def _webhook_internal_token() -> str:
  return os.getenv("WEBHOOK_INTERNAL_TOKEN", "").strip()


def _require_integrations() -> None:
  if not _store_url() or len(_store_token()) < 32:
    raise AuthorityError(503, "Trusted merchant STORE_URL/STORE_API_TOKEN is not configured")
  charge = _store_charge_token()
  if len(charge) < 32 or charge == _store_token():
    raise AuthorityError(503, "Trusted merchant STORE_CHARGE_TOKEN must be set and distinct")
  if not _webhook_url() or len(_webhook_internal_token()) < 32:
    raise AuthorityError(503, "Local payment rail WEBHOOK_URL/WEBHOOK_INTERNAL_TOKEN is not configured")
  parsed = urlsplit(_store_url())
  if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
      or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
    raise AuthorityError(503, "Trusted merchant must use a configured HTTP origin")


def _uuid_text(value: Any) -> str:
  if isinstance(value, UUID):
    return value.hex
  return str(value).replace("-", "")


def _checkout_url(checkout_id: str) -> str:
  # Checkout identifiers are data, never paths/URLs selected by the agent.
  if checkout_id in {".", ".."}:
    raise AuthorityError(422, "Invalid checkout identifier")
  return f"{_store_url()}/api/checkouts/{quote(checkout_id, safe='')}"


def _fetch_store_checkout(checkout_id: str) -> dict[str, Any]:
  try:
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
      res = client.get(
        _checkout_url(checkout_id),
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


def _merchant_trust_present(store: dict[str, Any]) -> bool:
  return bool(
    store.get("ownership_authenticated") is True
    and store.get("frozen") is True
    and store.get("expired") is False
    and isinstance(store.get("user_id"), str)
    and isinstance(store.get("session_id"), str)
    and isinstance(store.get("revision"), int)
    and store["revision"] >= 1
    and isinstance(store.get("expires_at"), str)
  )


def _store_charge_headers() -> dict[str, str]:
  return {
    "Authorization": f"Bearer {_store_charge_token()}",
    "Content-Type": "application/json",
    "Accept": "application/json",
  }


def _establish_checkout_trust(
  store: dict[str, Any],
  *,
  user_id: str,
  session_id: str,
) -> dict[str, Any]:
  """Own + freeze at the merchant before treating evidence as authenticated."""
  checkout_id = store["checkout_id"]
  if store.get("expired") is True:
    raise AuthorityError(409, "Trusted checkout expired")
  owner = store.get("user_id")
  session = store.get("session_id")
  if owner is not None and owner != user_id:
    raise AuthorityError(403, "Trusted checkout belongs to a different user")
  if session is not None and owner == user_id and session != session_id:
    raise AuthorityError(403, "Trusted checkout belongs to a different shopping session")
  if (
    _merchant_trust_present(store)
    and store.get("user_id") == user_id
    and store.get("session_id") == session_id
  ):
    return store
  try:
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
      if owner is None:
        owned = client.post(
          f"{_checkout_url(checkout_id)}/own",
          headers=_store_charge_headers(),
          json={"user_id": user_id, "session_id": session_id},
        )
        if owned.status_code >= 400:
          raise AuthorityError(502, "Trusted merchant rejected checkout ownership")
        store = owned.json()
      if store.get("frozen") is not True:
        frozen = client.post(
          f"{_checkout_url(checkout_id)}/freeze",
          headers=_store_charge_headers(),
          json={"expected_facts_hash": store["facts_hash"]},
        )
        if frozen.status_code >= 400:
          raise AuthorityError(502, "Trusted merchant rejected checkout freeze")
        store = frozen.json()
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Trusted merchant unreachable while establishing checkout trust") from exc
  if not isinstance(store, dict) or store.get("checkout_id") != checkout_id:
    raise AuthorityError(502, "Trusted merchant returned an invalid trusted checkout")
  if not _merchant_trust_present(store) or store.get("user_id") != user_id:
    raise AuthorityError(502, "Trusted merchant did not authenticate checkout ownership")
  return store


def _map_checkout_facts(store, *, user_id, payment_id, now):
  if store.get("status") != "open" or store.get("currency") != "USD":
    raise ValueError("Invalid checkout state or currency")
  lines = store["line_items"]
  if not isinstance(lines, list) or not lines:
    raise AuthorityError(502, "Trusted checkout missing line items")
  items = []
  for line in lines:
    if not isinstance(line, dict):
      raise AuthorityError(502, "Trusted checkout has invalid line items")
    if set(line) != {"product_id", "sku", "name", "category", "quantity", "price_cents",
                     "recurring", "subscription", "billing_interval", "attributes"}:
      raise ValueError("Unexpected canonical line item fields")
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
  trusted = _merchant_trust_present(store) and store.get("user_id") == user_id
  if trusted:
    try:
      expires = datetime.fromisoformat(str(store["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
      raise ValueError("Invalid merchant checkout expiry") from exc
    if expires.tzinfo is None or expires <= now:
      raise ValueError("Merchant checkout expired")
    revision = int(store["revision"])
    session_id = str(store["session_id"])
    owner_id = str(store["user_id"])
  else:
    # Legacy observation path for unit fixtures without merchant trust fields.
    expires = now + CHECKOUT_TTL
    revision = 1
    session_id = f"ses_{store['checkout_id']}"
    owner_id = user_id
  return CheckoutSnapshot(
    checkout_id=str(store["checkout_id"]),
    revision=revision,
    purchase_attempt_id=payment_id,
    user_id=owner_id,
    merchant_id=MERCHANT_ID,
    session_id=session_id,
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
      url=_checkout_url(store['checkout_id']),
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


def _seed_grant(grant: AuthorizationGrant, *, run_id: str) -> None:
  payload = grant.model_dump(mode="json")
  payload["run_id"] = run_id
  try:
    with httpx.Client(timeout=5.0) as client:
      res = client.put(
        f"{_webhook_url()}/internal/grants",
        headers={
          "Authorization": f"Bearer {_webhook_internal_token()}",
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        json=payload,
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
  authorization_event_id: str,
) -> None:
  body = {
    "payment_id": payment_id,
    "grant_id": grant.grant_id,
    "instrument_token": grant.payment_instrument_id,
    "merchant_binding_id": grant.merchant_binding_id,
    "checkout_hash": grant.verified_checkout_hash,
    "authorized_amount_cents": grant.authorized_amount_cents,
    "expires_at": grant.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    "authorization_event_id": authorization_event_id,
  }
  try:
    with httpx.Client(timeout=5.0) as client:
      res = client.post(
        f"{_store_url()}/api/checkouts/{checkout_id}/bind",
        headers=_store_charge_headers(),
        json=body,
      )
  except httpx.HTTPError as exc:
    raise AuthorityError(502, "Trusted merchant unreachable while binding checkout") from exc
  if res.status_code >= 400:
    raise AuthorityError(502, "Trusted merchant rejected checkout binding")


def _build_grant(
  *,
  operation: dict[str, Any],
  mandate: PurchaseMandate,
  checkout: CheckoutSnapshot,
  verification: CheckoutVerification,
  store_facts_hash: str,
  now: datetime,
) -> AuthorizationGrant:
  """One-use local-rail grant bound to frozen merchant facts_hash."""
  grant_expires = min(
    now + timedelta(minutes=30),
    mandate.valid_until,
    checkout.expires_at,
  )
  if grant_expires <= now:
    raise AuthorityError(409, "Checkout or mandate expired before grant issuance")
  instrument = "ins_" + _uuid_text(operation["instrument_reference"])
  return AuthorizationGrant(
    grant_id=str(operation["grant_reference"]),
    payment_id=operation["id"],
    mandate_id=mandate.id,
    mandate_version=mandate.version,
    mandate_hash=mandate.canonical_payload_hash,
    user_id=mandate.user_id,
    verification_id=verification.id,
    verified_checkout_id=checkout.checkout_id,
    verified_checkout_hash=store_facts_hash,
    payment_instrument_id=instrument,
    merchant_id=MERCHANT_ID,
    merchant_descriptor=checkout.merchant.descriptor,
    mcc=checkout.merchant.mcc,
    authorized_amount_cents=checkout.total_cents,
    currency=checkout.currency,
    merchant_binding_id=f"bind_{operation['id']}",
    bound_at=now,
    issued_at=now,
    expires_at=grant_expires,
    mandate_expires_at=mandate.valid_until,
    checkout_expires_at=checkout.expires_at,
    status=GrantStatus.ISSUED,
  )


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


def request_payment(
  conn, body: PaymentProposal, principal: Principal
) -> tuple[PaymentResponse, dict[str, str] | None]:
  """Returns (response, once-only secrets). Secrets are only set on fresh approve."""
  require_role(principal, "agent")
  if body.run_id is None:
    raise AuthorityError(422, "A registered run_id is required")
  mandate = _lock_payment_authority(conn, body, principal)
  operation = prepare(conn, body, principal, mandate)
  if operation["state"] != "prepared":
    return _original_response(conn, operation), None
  _require_integrations()
  _checkout_url(body.checkout_id)
  # This is the durability boundary. No merchant request (including read-only
  # retrieval) happens before the stable identity and audit event are committed.
  conn.commit()
  try:
    store = _fetch_store_checkout(body.checkout_id)
    if store.get("checkout_id") != body.checkout_id:
      raise AuthorityError(502, "Trusted merchant returned a different checkout")
    store = _establish_checkout_trust(
      store,
      user_id=principal.user_id,
      session_id=f"ses_{body.run_id}",
    )
    checkout = _map_checkout(store, user_id=principal.user_id, payment_id=operation["id"], now=utc_now())
    source_facts = {key: store[key] for key in (
      "checkout_id", "currency", "line_items", "mcc", "merchant_descriptor",
      "recurring", "total_cents", "facts_hash", "status",
    )}
    source_facts.update({
      "user_id": store.get("user_id"),
      "session_id": store.get("session_id"),
      "revision": store.get("revision"),
      "frozen": store.get("frozen"),
      "expires_at": store.get("expires_at"),
      "ownership_authenticated": store.get("ownership_authenticated"),
    })
    if canonical_json(sanitize_event_data(source_facts)) != canonical_json(source_facts):
      raise AuthorityError(502, "Trusted checkout contains sensitive data")
  except AuthorityError as error:
    # A failed GET cannot have spent funds. Save its terminal safe error so a
    # retry does not silently replace the candidate or keep making network calls.
    operation, _ = _relock_operation(conn, body, principal, operation)
    if operation["state"] != "prepared":
      return _original_response(conn, operation), None
    finish(conn, operation, "blocked", "checkout_source_unavailable", error=error)
    conn.commit()
    raise

  operation, mandate = _relock_operation(conn, body, principal, operation)
  if operation["state"] != "prepared":
    saved = conn.execute("SELECT source_hash FROM checkout_observations WHERE payment_id=%s", (operation["id"],)).fetchone()
    if saved and saved["source_hash"] != source_facts["facts_hash"]:
      raise AuthorityError(409, "Concurrent checkout observation conflicts with the original evidence")
    return _original_response(conn, operation), None
  now = utc_now()
  checkout_authenticated = _merchant_trust_present(store) and store.get("user_id") == principal.user_id
  verification = verify_checkout(
    mandate, checkout, now=now, confirmation_valid=_confirmation_valid(conn, mandate),
    checkout_authenticated=checkout_authenticated,
    successful_purchases=_successful_purchases(conn, principal.user_id, mandate),
  )

  if verification.decision != VerificationDecision.VERIFIED:
    response = PaymentResponse(
      id=operation["id"],
      status="blocked",
      reasons=verification.reasons,
      verification_id=verification.id,
    )
    persist_observation(conn, operation, checkout, source_facts, financial_authority=False)
    _persist(
      conn, payment_id=operation["id"], principal=principal, mandate=mandate,
      checkout_id=body.checkout_id, run_id=body.run_id, status="blocked",
      verification=verification, grant=None, instrument_token=None,
      checkout_hash=checkout.checkout_hash, response=response,
    )
    finish(conn, operation, "blocked", verification.reasons[0] if verification.reasons else "verification_blocked")
    return response, None

  event_id = "evt_" + _uuid_text(operation["authorization_event_id"])
  grant = _build_grant(
    operation=operation,
    mandate=mandate,
    checkout=checkout,
    verification=verification,
    store_facts_hash=str(store["facts_hash"]),
    now=now,
  )
  # Merchant bind before Valkey install so a usable grant always has correlation.
  _bind_store(
    checkout_id=body.checkout_id,
    payment_id=operation["id"],
    grant=grant,
    authorization_event_id=event_id,
  )
  _seed_grant(grant, run_id=body.run_id)
  response = PaymentResponse(
    id=operation["id"],
    status="approved",
    reasons=(),
    verification_id=verification.id,
    grant_id=grant.grant_id,
  )
  persist_observation(conn, operation, checkout, source_facts, financial_authority=True)
  _persist(
    conn, payment_id=operation["id"], principal=principal, mandate=mandate,
    checkout_id=body.checkout_id, run_id=body.run_id, status="approved",
    verification=verification, grant=grant, instrument_token=grant.payment_instrument_id,
    checkout_hash=checkout.checkout_hash, response=response,
  )
  finish(conn, operation, "authorized", "grant_issued_local_rail")
  once = {
    "instrument_token": grant.payment_instrument_id,
    "authorization_event_id": event_id,
    "rail": "local_payment_rail_simulator",
  }
  return response, once


def _lock_payment_authority(conn, body, principal):
  lock_user_authority(conn, principal.user_id)
  run = conn.execute(
    """SELECT * FROM agent_runs WHERE id=%s AND user_id=%s
    AND agent_id=%s AND mandate_id=%s""",
    (body.run_id, principal.user_id, principal.agent_id, body.mandate_id),
  ).fetchone()
  if run is None:
    raise AuthorityError(404, "Registered run not found")
  if conn.execute("SELECT run_id FROM run_cancellations WHERE run_id=%s", (body.run_id,)).fetchone():
    raise AuthorityError(409, "Run has been stopped")
  now = utc_now()
  mandate = current_mandate(conn, body.mandate_id, principal, now=now, lock=True)
  if (mandate.status.value != "active" or not mandate.valid_from <= utc_now() < mandate.valid_until
      or run["mandate_version"] != mandate.version
      or run["record"]["mandate_hash"] != mandate.canonical_payload_hash):
    raise AuthorityError(409, "Registered run authority is no longer current")
  return mandate


def _relock_operation(conn, body, principal, operation):
  try:
    mandate = _lock_payment_authority(conn, body, principal)
  except AuthorityError:
    # Includes expiry, stale run/version and account/run cancellation. This
    # terminal cancellation commits even though the HTTP request returns 409.
    cancel_prepared(conn, principal.user_id, run_id=body.run_id, reason="authority_changed")
    conn.commit()
    raise
  latest = conn.execute("SELECT * FROM payment_operations WHERE id=%s FOR UPDATE", (operation["id"],)).fetchone()
  if (latest["mandate_version"] != mandate.version
      or latest["mandate_hash"] != mandate.canonical_payload_hash):
    raise AuthorityError(409, "Payment operation authority changed")
  return latest, mandate


def _original_response(conn, operation):
  if operation["state"] in {"cancelled", "reconciling"}:
    raise AuthorityError(409, "Payment operation is cancelled or requires reconciliation; no purchase is authorized")
  if operation["error_status"]:
    raise AuthorityError(operation["error_status"], operation["error_detail"])
  row = conn.execute("SELECT record FROM payment_attempts WHERE id=%s", (operation["id"],)).fetchone()
  if row is None:
    raise AuthorityError(503, "Payment operation outcome is unavailable; no replacement is authorized")
  response = PaymentResponse.model_validate(row["record"])
  if response.id != operation["id"] or response.payment_result is not None:
    raise AuthorityError(503, "Stored preflight outcome failed integrity verification")
  if operation["state"] == "authorized":
    if response.status != "approved" or response.grant_id is None:
      raise AuthorityError(503, "Stored authorization outcome failed integrity verification")
  elif response.status != "blocked" or response.grant_id is not None:
    raise AuthorityError(503, "Stored preflight outcome failed integrity verification")
  return response


def get_payment(conn, payment_id: str, principal: Principal) -> dict[str, Any]:
  require_role(principal, "agent")
  row = conn.execute(
    """SELECT p.record,o.state,o.revision,o.reason FROM payment_operations o
       LEFT JOIN payment_attempts p ON p.id=o.id WHERE o.id=%s AND o.user_id=%s AND o.agent_id=%s""",
    (payment_id, principal.user_id, principal.agent_id),
  ).fetchone()
  if row is None:
    legacy = conn.execute("SELECT record FROM payment_attempts WHERE id=%s AND user_id=%s AND agent_id=%s",
                          (payment_id, principal.user_id, principal.agent_id)).fetchone()
    if not legacy:
      raise AuthorityError(404, "Payment not found")
    payload = dict(legacy["record"])
    authorized = payload.get("status") == "approved"
  else:
    payload = dict(row["record"] or PaymentResponse(id=payment_id, status="blocked",
                   reasons=(row["reason"] or "operation_pending",)).model_dump(mode="json"))
    authorized = row["state"] == "authorized"
    payload["operation"] = {
      "state": row["state"],
      "revision": row["revision"],
      "financial_authority": authorized,
    }
  # Grant approval is not a paid receipt; instrument is never re-disclosed on GET.
  payload["authorization_status"] = "grant_issued" if authorized else "unverified"
  payload["payment_execution"] = "awaiting_merchant_complete" if authorized else "unavailable"
  payload.pop("instrument_token", None)
  return payload
