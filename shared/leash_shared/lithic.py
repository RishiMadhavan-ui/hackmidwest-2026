"""Lithic sandbox transport: SINGLE_USE purchase cards and legacy card reads.

Program eligibility and live sandbox behavior require external verification.
Credit-like headroom is card spend_limit minus
non-declined transaction pending/settled amounts (integer cents).

Never log or persist PAN/CVV.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

# Fixed sandbox placeholders for KYC_EXEMPT fields not collected on signup.
_SANDBOX_ADDRESS1 = "123 Main Street"
_SANDBOX_CITY = "New York"
_SANDBOX_STATE = "NY"
_SANDBOX_PHONE = "+15555550100"

# Statuses that do not consume spend-limit headroom.
_NON_SPEND_STATUSES = frozenset(
    {
        "DECLINED",
        "VOIDED",
        "EXPIRED",
        "REJECTED",
    }
)

DEFAULT_SPEND_LIMIT_CENTS = 50_000  # $500 forever limit for demo


class LithicError(Exception):
    """Lithic API or configuration failure (safe message for callers)."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _api_key() -> str:
    key = os.environ.get("LITHIC_API_KEY", "").strip()
    if not key:
        raise LithicError("LITHIC_API_KEY is not configured")
    return key


def _base_url() -> str:
    env = os.environ.get("LITHIC_ENVIRONMENT", "sandbox").strip().lower()
    if env != "sandbox":
        raise LithicError("Only LITHIC_ENVIRONMENT=sandbox is supported")
    return "https://sandbox.lithic.com"


def _headers() -> dict[str, str]:
    return {
        "Authorization": _api_key(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def default_spend_limit_cents() -> int:
    raw = os.environ.get("LITHIC_DEFAULT_SPEND_LIMIT_CENTS", "").strip()
    if not raw:
        return DEFAULT_SPEND_LIMIT_CENTS
    try:
        value = int(raw)
    except ValueError as exc:
        raise LithicError("LITHIC_DEFAULT_SPEND_LIMIT_CENTS must be an integer") from exc
    if value < 0:
        raise LithicError("LITHIC_DEFAULT_SPEND_LIMIT_CENTS must be >= 0")
    return value


def create_account_holder(
    email: str,
    first_name: str,
    last_name: str,
    postal_code: str,
    *,
    external_id: str | None = None,
) -> dict[str, str]:
    """Create a KYC_EXEMPT account holder; return Lithic tokens.

    Returns keys: account_token, account_holder_token.
    """
    tos = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    body: dict[str, Any] = {
        "workflow": "KYC_EXEMPT",
        "kyc_exemption_type": "PREPAID_CARD_USER",
        "tos_timestamp": tos,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": _SANDBOX_PHONE,
        "address": {
            "address1": _SANDBOX_ADDRESS1,
            "city": _SANDBOX_CITY,
            "state": _SANDBOX_STATE,
            "postal_code": postal_code,
            "country": "USA",
        },
    }
    if external_id:
        body["external_id"] = external_id

    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.post("/v1/account_holders", headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc

    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic account holder create failed ({res.status_code})"),
            status_code=res.status_code,
        )

    account_token = data.get("account_token") or (data.get("account") or {}).get("token")
    holder_token = data.get("token") or data.get("account_holder_token")
    if not account_token or not holder_token:
        raise LithicError("Lithic response missing account tokens")

    return {
        "account_token": str(account_token),
        "account_holder_token": str(holder_token),
    }


_ALLOWED_SPEND_DURATIONS = frozenset(
    {"TRANSACTION", "MONTHLY", "ANNUALLY", "FOREVER"}
)
_ALLOWED_CARD_TYPES = frozenset({"SINGLE_USE"})


def create_virtual_card(
    account_token: str,
    *,
    idempotency_key: str,
    spend_limit_cents: int | None = None,
    spend_limit_duration: str = "TRANSACTION",
    card_type: str = "SINGLE_USE",
    memo: str | None = None,
    tags: dict[str, str] | None = None,
    include_payment_details: bool = False,
) -> dict[str, Any]:
    """Transport only; the backend must verify and persist issuance first.

    The historical function name is retained. Every new purchase card is
    SINGLE_USE with an explicit positive verified limit and a caller-persisted
    UUID key. Never generate a replacement key after an ambiguous outcome.

    By default returns token metadata only (no PAN/CVV). When
    ``include_payment_details=True`` (sandbox once-only delivery to an
    authorized caller), pan/exp/cvv are included in the return dict â€” never log them.
    """
    limit = spend_limit_cents
    if type(limit) is not int or limit <= 0:
        raise LithicError("spend_limit_cents must be an explicit positive integer")
    try:
        if not isinstance(idempotency_key, str) or str(UUID(idempotency_key)) != idempotency_key.lower():
            raise ValueError
    except (ValueError, AttributeError):
        raise LithicError("idempotency_key must be a persisted UUID") from None

    duration = spend_limit_duration.strip().upper() if isinstance(spend_limit_duration, str) else ""
    if duration not in _ALLOWED_SPEND_DURATIONS:
        raise LithicError(
            f"spend_limit_duration must be one of {sorted(_ALLOWED_SPEND_DURATIONS)}"
        )

    ctype = card_type.strip().upper() if isinstance(card_type, str) else ""
    if ctype not in _ALLOWED_CARD_TYPES:
        raise LithicError(f"card_type must be one of {sorted(_ALLOWED_CARD_TYPES)}")

    body: dict[str, Any] = {
        "type": ctype,
        "account_token": account_token,
        "state": "OPEN",
        "spend_limit": limit,
        "spend_limit_duration": duration,
    }
    if memo:
        body["memo"] = memo
    if tags:
        body["tags"] = tags

    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.post("/v1/cards", headers={**_headers(), "Idempotency-Key": idempotency_key}, json=body)
    except httpx.HTTPError:
        raise LithicError("Card issuance outcome unknown; reconcile the original operation") from None

    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            f"Lithic card create failed ({res.status_code}); reconcile the original operation",
            status_code=res.status_code,
        )

    token = data.get("token")
    if (
        res.status_code not in {200, 201}
        or not isinstance(token, str) or not token
        or data.get("type") != "SINGLE_USE"
        or type(data.get("spend_limit")) is not int or data["spend_limit"] != limit
        or data.get("spend_limit_duration") != duration
        or data.get("account_token") != account_token
        or data.get("state") not in {"OPEN", "PAUSED"}
    ):
        raise LithicError("Card issuance response unverified; reconcile the original operation")

    out: dict[str, Any] = {
        "card_token": str(token),
        "last_four": str(data.get("last_four") or ""),
        "spend_limit_cents": data["spend_limit"],
        "spend_limit_duration": data["spend_limit_duration"],
        "card_type": "SINGLE_USE",
        "account_token": data["account_token"],
        "state": data["state"],
        "provider": "lithic_sandbox",
    }
    if include_payment_details:
        pan = data.get("pan")
        cvv = data.get("cvv")
        if not pan or not cvv:
            raise LithicError("Lithic card response missing once-only payment details")
        out["pan"] = str(pan)
        out["cvv"] = str(cvv)
        out["exp_month"] = str(data.get("exp_month") or "")
        out["exp_year"] = str(data.get("exp_year") or "")
    return out


def get_card(card_token: str) -> dict[str, Any]:
    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.get(f"/v1/cards/{card_token}", headers=_headers())
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc

    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic get card failed ({res.status_code})"),
            status_code=res.status_code,
        )
    if not isinstance(data, dict):
        raise LithicError("Lithic get card returned unexpected body")
    return data


def list_card_transactions(card_token: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    """List transactions for a card (paginated)."""
    rows: list[dict[str, Any]] = []
    starting_after: str | None = None

    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            while True:
                params: dict[str, Any] = {
                    "card_token": card_token,
                    "page_size": min(max(page_size, 1), 100),
                }
                if starting_after:
                    params["starting_after"] = starting_after
                res = client.get("/v1/transactions", headers=_headers(), params=params)
                data = _json_or_empty(res)
                if res.status_code >= 400:
                    raise LithicError(
                        _error_message(
                            data, f"Lithic list transactions failed ({res.status_code})"
                        ),
                        status_code=res.status_code,
                    )
                batch = _as_list(data)
                if not batch:
                    break
                rows.extend(batch)
                if len(batch) < params["page_size"]:
                    break
                last_token = batch[-1].get("token")
                if not last_token or last_token == starting_after:
                    break
                starting_after = str(last_token)
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc

    return rows


def get_spend_limit_balance(
    card_token: str,
    *,
    spend_limit_cents: int | None = None,
) -> dict[str, Any]:
    """Remaining headroom vs card spend_limit (credit-like, not a prepaid ledger).

    available_cents = max(0, limit - pending - settled)
    pending_cents   = sum of pending_amount on spend-counting txns
    total_cents     = spend limit (credit ceiling)
    spent_cents     = pending + settled
    """
    card = get_card(card_token)
    limit = (
        spend_limit_cents
        if spend_limit_cents is not None
        else int(card.get("spend_limit") or 0)
    )
    pending = 0
    settled = 0
    for txn in list_card_transactions(card_token):
        status = str(txn.get("status") or "").upper()
        if status in _NON_SPEND_STATUSES:
            continue
        pending += int(txn.get("pending_amount") or 0)
        settled += int(txn.get("settled_amount") or 0)

    spent = pending + settled
    available = max(0, limit - spent)
    return {
        "currency": "USD",
        "available_cents": available,
        "pending_cents": pending,
        "total_cents": limit,
        "spent_cents": spent,
        "limit_cents": limit,
        "last_four": str(card.get("last_four") or ""),
        "provider": "lithic_sandbox",
        "model": "card_spend_limit",
    }


def update_card_state(card_token: str, state: str) -> dict[str, Any]:
    """Set card state (OPEN / PAUSED / CLOSED / PENDING_FULFILLMENT / PENDING_ACTIVATION)."""
    desired = state.strip().upper()
    allowed = {"OPEN", "PAUSED", "CLOSED", "PENDING_FULFILLMENT", "PENDING_ACTIVATION"}
    if desired not in allowed:
        raise LithicError(f"card state must be one of {sorted(allowed)}")
    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.patch(
                f"/v1/cards/{card_token}",
                headers=_headers(),
                json={"state": desired},
            )
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc
    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic update card failed ({res.status_code})"),
            status_code=res.status_code,
        )
    if not isinstance(data, dict):
        raise LithicError("Lithic update card returned unexpected body")
    return data


def enroll_asa_responder(url: str) -> dict[str, Any]:
    """Enroll a publicly reachable ASA responder URL (sandbox self-serve)."""
    body = {"type": "AUTH_STREAM_ACCESS", "url": url}
    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.post("/v1/responder_endpoints", headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc
    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic ASA enroll failed ({res.status_code})"),
            status_code=res.status_code,
        )
    return data if isinstance(data, dict) else {"raw": data}


def get_asa_hmac_secret() -> str:
    """Retrieve the program ASA HMAC secret (enables webhook-* headers on ASA)."""
    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.get("/v1/auth_stream/secret", headers=_headers())
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc
    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic ASA secret retrieve failed ({res.status_code})"),
            status_code=res.status_code,
        )
    if not isinstance(data, dict):
        raise LithicError("Lithic ASA secret response unexpected")
    secret = data.get("secret") or data.get("key") or data.get("asa_client_secret")
    if not secret:
        raise LithicError("Lithic ASA secret response missing secret")
    return str(secret)


def simulate_authorization(
    *,
    card_token: str,
    amount_cents: int,
    descriptor: str,
    mcc: str,
    merchant_acceptor_id: str | None = None,
) -> dict[str, Any]:
    """Sandbox: simulate an authorization that Lithic routes to the enrolled ASA endpoint."""
    if amount_cents < 0:
        raise LithicError("amount_cents must be >= 0")
    body: dict[str, Any] = {
        "card_token": card_token,
        "amount": amount_cents,
        "descriptor": descriptor,
        "mcc": mcc,
    }
    if merchant_acceptor_id:
        body["merchant_acceptor_id"] = merchant_acceptor_id
    try:
        with httpx.Client(base_url=_base_url(), timeout=30.0) as client:
            res = client.post("/v1/simulate/authorize", headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc
    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic simulate authorize failed ({res.status_code})"),
            status_code=res.status_code,
        )
    return data if isinstance(data, dict) else {"raw": data}


def _as_list(data: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    inner = data.get("data")
    if isinstance(inner, list):
        return [row for row in inner if isinstance(row, dict)]
    return []


def _json_or_empty(res: httpx.Response) -> dict[str, Any] | list[Any]:
    try:
        body = res.json()
    except ValueError:
        return {}
    if isinstance(body, (dict, list)):
        return body
    return {}


def _error_message(data: dict[str, Any] | list[Any], fallback: str) -> str:
    if isinstance(data, dict):
        for key in ("message", "detail", "error"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return fallback
