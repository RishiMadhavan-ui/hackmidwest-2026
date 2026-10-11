"""Owner-scoped card metadata; direct card issuance is closed.

Payment instruments must be issued internally after mandate/checkout/grant
verification. Caller-supplied limits and correlations cannot authorize issuance.
"""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/cards", tags=["cards"])
bearer_scheme = HTTPBearer(auto_error=False)

# Exact checkout totals can be small; upper bound matches signup credit ceiling.
MIN_SPEND_LIMIT_CENTS = 1
MAX_SPEND_LIMIT_CENTS = 10_000_000

SpendDuration = Literal["TRANSACTION", "MONTHLY", "ANNUALLY", "FOREVER"]


class IssueCardRequest(BaseModel):
    """Legacy request shape retained only to return a clear fail-closed error."""

    model_config = ConfigDict(extra="forbid")

    spend_limit_cents: int = Field(ge=MIN_SPEND_LIMIT_CENTS, le=MAX_SPEND_LIMIT_CENTS)
    spend_limit_duration: SpendDuration = "TRANSACTION"
    single_use: bool = True
    memo: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Legacy caller claim; never authorizes direct issuance",
    )
    # Optional compatibility field; never selects another owner.
    user_id: str | None = None


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
        os.getenv("AGENT_TOKEN_SHOPPER_SCRIPTED", "").strip(),
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent and service credentials cannot access card management",
        )

    # Use the existing account authenticator: validate the JWT UUID and require
    # a real user, rather than trusting a token subject or a caller-selected id.
    user_id = get_current_user(credentials).id
    if body_user_id is not None and body_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id does not match authenticated user",
        )
    return user_id


@router.post("", deprecated=True, response_model=None, status_code=status.HTTP_409_CONFLICT)
def issue_card(
    body: IssueCardRequest,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> None:
    """Reject direct issuance until the verified backend payment flow exists."""
    _resolve_user_id(credentials, body_user_id=body.user_id)
    # A human login and arbitrary correlation string are not purchase authority.
    # No provider or SQL issuance call is reachable through this HTTP route.
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Direct card issuance is disabled; payment instruments require the verified payment flow",
    )


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
        from activity import emit_for_auth_user
        from leash_shared.events import EventType

        emit_for_auth_user(
            conn,
            auth_user_id=user_id,
            event_type=EventType.CARD_ISSUED.value,
            data={
                "last_four": card.get("last_four") or None,
                "spend_limit_cents": int(card["spend_limit_cents"]),
                "spend_limit_duration": card["spend_limit_duration"],
                "card_type": card["card_type"],
                "correlation_id": body.correlation_id,
                "source": "issue_card",
                "provider": "lithic_sandbox",
            },
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
