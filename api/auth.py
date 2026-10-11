import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from db import get_conn
from leash_shared.lithic import (
    LithicError,
    create_account_holder,
    create_virtual_card,
    get_spend_limit_balance,
)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
JWT_ALG = "HS256"
MIN_PASSWORD_LEN = 8
# Forever card spend_limit bounds (integer cents).
MIN_SPEND_LIMIT_CENTS = 1_000  # $10
MAX_SPEND_LIMIT_CENTS = 10_000_000  # $100,000
# US ZIP: 12345 or 12345-6789; also allow short alphanumeric postal strings.
POSTAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s-]{2,11}$")

_USER_SELECT_COLS = """
    id, email, password_hash, first_name, last_name, postal_code,
    lithic_account_token, lithic_account_holder_token,
    lithic_card_token, lithic_card_last_four, lithic_spend_limit_cents
"""


class AuthCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=3, max_length=12)
    spend_limit_cents: int = Field(
        ge=MIN_SPEND_LIMIT_CENTS,
        le=MAX_SPEND_LIMIT_CENTS,
        description="Forever virtual-card spend limit in integer cents",
    )


class UserOut(BaseModel):
    id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    postal_code: str | None = None
    lithic_linked: bool = False
    lithic_card_last_four: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class BalanceOut(BaseModel):
    """Credit-like headroom against the sandbox virtual card spend_limit."""

    currency: str
    available_cents: int  # remaining headroom
    pending_cents: int
    total_cents: int  # spend limit (credit ceiling)
    spent_cents: int = 0
    limit_cents: int = 0
    last_four: str | None = None
    provider: str = "lithic_sandbox"
    model: str = "card_spend_limit"


def _require_jwt_secret() -> str:
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    return JWT_SECRET


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, _require_jwt_secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _require_jwt_secret(), algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def _user_out(row: dict) -> UserOut:
    last_four = row.get("lithic_card_last_four")
    return UserOut(
        id=str(row["id"]),
        email=row["email"],
        first_name=row.get("first_name"),
        last_name=row.get("last_name"),
        postal_code=row.get("postal_code"),
        lithic_linked=bool(row.get("lithic_card_token")),
        lithic_card_last_four=str(last_four) if last_four else None,
    )


def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_USER_SELECT_COLS} FROM users WHERE email = %s",
            (email.lower(),),
        ).fetchone()
    return row


def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, email, first_name, last_name, postal_code,
                   lithic_account_token, lithic_account_holder_token,
                   lithic_card_token, lithic_card_last_four, lithic_spend_limit_cents
            FROM users WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
    return row


def delete_user(user_id: uuid.UUID | str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
        conn.commit()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> UserOut:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    try:
        user_id = str(uuid.UUID(str(user_id)))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    row = get_user_by_id(str(user_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return _user_out(row)


def _token_for_row(row: dict) -> TokenResponse:
    user = _user_out(row)
    return TokenResponse(
        access_token=create_access_token(user.id, user.email),
        user=user,
    )


def _normalize_postal(postal_code: str) -> str:
    cleaned = postal_code.strip().upper()
    if not POSTAL_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid postal code",
        )
    return cleaned


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest) -> TokenResponse:
    _require_jwt_secret()
    email = body.email.lower().strip()
    first_name = body.first_name.strip()
    last_name = body.last_name.strip()
    postal_code = _normalize_postal(body.postal_code)

    if not first_name or not last_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="First name and last name are required",
        )
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password exceeds bcrypt's 72-byte limit",
        )
    if get_user_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user_id = uuid.uuid4()
    password_hash = hash_password(body.password)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, first_name, last_name, postal_code)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, email, password_hash, first_name, last_name, postal_code),
        )
        conn.commit()

    try:
        tokens = create_account_holder(
            email,
            first_name,
            last_name,
            postal_code,
            external_id=str(user_id),
        )
        card = create_virtual_card(
            tokens["account_token"],
            spend_limit_cents=body.spend_limit_cents,
            memo=f"LEASH sandbox · {email}",
        )
    except LithicError as exc:
        delete_user(user_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lithic sandbox provisioning failed: {exc}",
        ) from exc

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE users SET
                lithic_account_token = %s,
                lithic_account_holder_token = %s,
                lithic_card_token = %s,
                lithic_card_last_four = %s,
                lithic_spend_limit_cents = %s
            WHERE id = %s
            """,
            (
                tokens["account_token"],
                tokens["account_holder_token"],
                card["card_token"],
                card.get("last_four") or None,
                int(card["spend_limit_cents"]),
                user_id,
            ),
        )
        conn.commit()

    row = get_user_by_id(str(user_id))
    assert row is not None
    return _token_for_row(row)


@router.post("/login", response_model=TokenResponse)
def login(body: AuthCredentials) -> TokenResponse:
    email = body.email.lower().strip()
    row = get_user_by_email(email)
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return _token_for_row(row)


@router.get("/me", response_model=UserOut)
def me(user: Annotated[UserOut, Depends(get_current_user)]) -> UserOut:
    return user


@router.get("/balance", response_model=BalanceOut)
def balance(user: Annotated[UserOut, Depends(get_current_user)]) -> BalanceOut:
    row = get_user_by_id(user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    card_token = row.get("lithic_card_token")
    if not card_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Lithic sandbox card linked to this user",
        )
    stored_limit = row.get("lithic_spend_limit_cents")
    try:
        bal = get_spend_limit_balance(
            str(card_token),
            spend_limit_cents=int(stored_limit) if stored_limit is not None else None,
        )
    except LithicError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lithic sandbox balance unavailable: {exc}",
        ) from exc
    return BalanceOut(**bal)
