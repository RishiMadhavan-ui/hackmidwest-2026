"""Lithic sandbox client: account holders, virtual cards, spend-limit headroom.

This sandbox program supports KYC_EXEMPT holders and virtual cards, but not
financial-account balances. Credit-like headroom is card spend_limit minus
non-declined transaction pending/settled amounts (integer cents).

Never log or persist PAN/CVV.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

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
    if env in ("", "sandbox"):
        return "https://sandbox.lithic.com"
    if env == "production":
        return "https://api.lithic.com"
    if env.startswith("http://") or env.startswith("https://"):
        return env.rstrip("/")
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
_ALLOWED_CARD_TYPES = frozenset({"VIRTUAL", "SINGLE_USE"})


def create_virtual_card(
    account_token: str,
    *,
    spend_limit_cents: int | None = None,
    spend_limit_duration: str = "FOREVER",
    card_type: str = "VIRTUAL",
    memo: str | None = None,
    tags: dict[str, str] | None = None,
    include_payment_details: bool = False,
) -> dict[str, Any]:
    """Issue an OPEN card on an account.

    By default returns token metadata only (no PAN/CVV). When
    ``include_payment_details=True`` (sandbox once-only delivery to an
    authorized caller), pan/exp/cvv are included in the return dict — never log them.
    """
    limit = default_spend_limit_cents() if spend_limit_cents is None else spend_limit_cents
    if limit < 0:
        raise LithicError("spend_limit_cents must be >= 0")

    duration = spend_limit_duration.strip().upper()
    if duration not in _ALLOWED_SPEND_DURATIONS:
        raise LithicError(
            f"spend_limit_duration must be one of {sorted(_ALLOWED_SPEND_DURATIONS)}"
        )

    ctype = card_type.strip().upper()
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
            res = client.post("/v1/cards", headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        raise LithicError("Lithic sandbox unreachable") from exc

    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise LithicError(
            _error_message(data, f"Lithic card create failed ({res.status_code})"),
            status_code=res.status_code,
        )

    token = data.get("token")
    if not token:
        raise LithicError("Lithic card response missing token")

    out: dict[str, Any] = {
        "card_token": str(token),
        "last_four": str(data.get("last_four") or ""),
        "spend_limit_cents": int(
            data.get("spend_limit") if data.get("spend_limit") is not None else limit
        ),
        "spend_limit_duration": str(data.get("spend_limit_duration") or duration),
        "card_type": str(data.get("type") or ctype),
        "account_token": str(data.get("account_token") or account_token),
        "state": str(data.get("state") or "OPEN"),
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
