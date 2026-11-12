import hmac
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

from shared.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_current_user_id(
    x_user_id: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
) -> uuid.UUID:
    expected = get_settings().internal_service_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        return uuid.UUID(x_user_id or "")
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
