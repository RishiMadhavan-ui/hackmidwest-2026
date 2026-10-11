"""On-demand Lithic sandbox virtual / single-use cards for purchase instruments.

Agents and authorized callers issue a fresh card on the user's existing Lithic
account_token. PAN/CVV are returned once in the create response and never stored.
"""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from auth import decode_token, get_user_by_id
from db import get_conn
from leash_shared.lithic import LithicError, create_virtual_card

router = APIRouter(prefix="/cards", tags=["cards"])
bearer_scheme = HTTPBearer(auto_error=False)

# Exact checkout totals can be small; upper bound matches signup credit ceiling.
MIN_SPEND_LIMIT_CENTS = 1
MAX_SPEND_LIMIT_CENTS = 10_000_000

SpendDuration = Literal["TRANSACTION", "MONTHLY", "ANNUALLY", "FOREVER"]


class IssueCardRequest(BaseModel):
    spend_limit_cents: int = Field(ge=MIN_SPEND_LIMIT_CENTS, le=MAX_SPEND_LIMIT_CENTS)
    spend_limit_duration: SpendDuration = "TRANSACTION"
    single_use: bool = True
    memo: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional checkout/grant correlation for Lithic tags + local record",
    )
    # Required when calling with AGENTS_SERVICE_TOKEN / AGENT_TOKEN_SHOPPER.
    user_id: str | None = None


class IssuedCardOut(BaseModel):
    card_token: str
    last_four: str
    spend_limit_cents: int
    spend_limit_duration: str
    card_type: str
    state: str
    account_token: str
    correlation_id: str | None = None
    provider: str = "lithic_sandbox"
    # Once-only sandbox payment details for the merchant / complete_checkout path.
    pan: str
    cvv: str
    exp_month: str
    exp_year: str
    details_returned_once: bool = True


class CardMetaOut(BaseModel):
    card_token: str
    last_four: str | None = None
    spend_limit_cents: int
    spend_limit_duration: str
    card_type: str
    state: str | None = None
    correlation_id: str | None = None
    created_at: str | None = None
    provider: str = "lithic_sandbox"


def _service_tokens() -> set[str]:
    tokens = {
        os.getenv("AGENTS_SERVICE_TOKEN", "").strip(),
        os.getenv("AGENT_TOKEN_SHOPPER", "").strip(),
    }
    return {t for t in tokens if t}


def _resolve_user_id(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    body_user_id: str | None,
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    token = credentials.credentials
    service = _service_tokens()
    if token in service:
        if not body_user_id or not body_user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id is required when calling with an agent service token",
            )
        return body_user_id.strip()

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if body_user_id and body_user_id.strip() and body_user_id.strip() != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id does not match authenticated user",
        )
    return str(user_id)


def _account_token_for_user(user_id: str) -> str:
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    account_token = row.get("lithic_account_token")
    if not account_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User has no Lithic sandbox account; complete signup first",
        )
    return str(account_token)


@router.post("", response_model=IssuedCardOut, status_code=status.HTTP_201_CREATED)
def issue_card(
    body: IssueCardRequest,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> IssuedCardOut:
    """Issue a fresh sandbox card on the user's Lithic account for one purchase.

    PAN/CVV are returned in this response only and are not persisted.
    """
    user_id = _resolve_user_id(credentials, body_user_id=body.user_id)
    account_token = _account_token_for_user(user_id)
    card_type = "SINGLE_USE" if body.single_use else "VIRTUAL"
    tags = {"leash_correlation": body.correlation_id} if body.correlation_id else None
    memo = body.memo or (
        f"LEASH instrument · {body.correlation_id}"
        if body.correlation_id
        else "LEASH per-transaction instrument"
    )

    try:
        card = create_virtual_card(
            account_token,
            spend_limit_cents=body.spend_limit_cents,
            spend_limit_duration=body.spend_limit_duration,
            card_type=card_type,
            memo=memo,
            tags=tags,
            include_payment_details=True,
        )
    except LithicError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lithic sandbox card issue failed: {exc}",
        ) from exc

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO lithic_cards (
                card_token, user_id, account_token, last_four,
                spend_limit_cents, spend_limit_duration, card_type,
                state, memo, correlation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                card["card_token"],
                user_id,
                card["account_token"],
                card.get("last_four") or None,
                int(card["spend_limit_cents"]),
                card["spend_limit_duration"],
                card["card_type"],
                card.get("state"),
                memo,
                body.correlation_id,
            ),
        )
        conn.commit()

    return IssuedCardOut(
        card_token=card["card_token"],
        last_four=card.get("last_four") or "",
        spend_limit_cents=int(card["spend_limit_cents"]),
        spend_limit_duration=card["spend_limit_duration"],
        card_type=card["card_type"],
        state=card.get("state") or "OPEN",
        account_token=card["account_token"],
        correlation_id=body.correlation_id,
        pan=card["pan"],
        cvv=card["cvv"],
        exp_month=card.get("exp_month") or "",
        exp_year=card.get("exp_year") or "",
    )


@router.get("", response_model=list[CardMetaOut])
def list_cards(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    user_id: str | None = None,
) -> list[CardMetaOut]:
    """List issued card metadata for a user (no PAN/CVV)."""
    resolved = _resolve_user_id(credentials, body_user_id=user_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT card_token, last_four, spend_limit_cents, spend_limit_duration,
                   card_type, state, correlation_id, created_at
            FROM lithic_cards
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (resolved,),
        ).fetchall()
    return [
        CardMetaOut(
            card_token=row["card_token"],
            last_four=row.get("last_four"),
            spend_limit_cents=int(row["spend_limit_cents"]),
            spend_limit_duration=row["spend_limit_duration"],
            card_type=row["card_type"],
            state=row.get("state"),
            correlation_id=row.get("correlation_id"),
            created_at=row["created_at"].isoformat() if row.get("created_at") else None,
        )
        for row in rows
    ]


@router.get("/{card_token}", response_model=CardMetaOut)
def get_card_meta(
    card_token: str,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    user_id: str | None = None,
) -> CardMetaOut:
    """Fetch issued card metadata (no PAN/CVV)."""
    resolved = _resolve_user_id(credentials, body_user_id=user_id)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT card_token, last_four, spend_limit_cents, spend_limit_duration,
                   card_type, state, correlation_id, created_at
            FROM lithic_cards
            WHERE card_token = %s AND user_id = %s
            """,
            (card_token, resolved),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found",
        )
    return CardMetaOut(
        card_token=row["card_token"],
        last_four=row.get("last_four"),
        spend_limit_cents=int(row["spend_limit_cents"]),
        spend_limit_duration=row["spend_limit_duration"],
        card_type=row["card_type"],
        state=row.get("state"),
        correlation_id=row.get("correlation_id"),
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
    )
