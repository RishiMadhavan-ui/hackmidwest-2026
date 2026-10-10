import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from db import get_conn

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
JWT_ALG = "HS256"
MIN_PASSWORD_LEN = 8


class AuthCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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


def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (email.lower(),),
        ).fetchone()
    return row


def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
    return row


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
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    row = get_user_by_id(str(user_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return UserOut(id=str(row["id"]), email=row["email"])


def _token_for_user(user_id: uuid.UUID | str, email: str) -> TokenResponse:
    uid = str(user_id)
    return TokenResponse(
        access_token=create_access_token(uid, email),
        user=UserOut(id=uid, email=email),
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: AuthCredentials) -> TokenResponse:
    _require_jwt_secret()
    email = body.email.lower().strip()
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password exceeds bcrypt's 72-byte limit")
    if get_user_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    user_id = uuid.uuid4()
    password_hash = hash_password(body.password)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (%s, %s, %s)",
            (user_id, email, password_hash),
        )
        conn.commit()
    return _token_for_user(user_id, email)


@router.post("/login", response_model=TokenResponse)
def login(body: AuthCredentials) -> TokenResponse:
    email = body.email.lower().strip()
    row = get_user_by_email(email)
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return _token_for_user(row["id"], row["email"])


@router.get("/me", response_model=UserOut)
def me(user: Annotated[UserOut, Depends(get_current_user)]) -> UserOut:
    return user
