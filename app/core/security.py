from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from itsdangerous import URLSafeSerializer, BadSignature
from passlib.context import CryptContext

from app.core.config import get_settings


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


class SessionSigner:
    def __init__(self) -> None:
        settings = get_settings()
        self.s = URLSafeSerializer(settings.SECRET_KEY, salt="pickems-session")
        self.cookie_name = settings.SESSION_COOKIE_NAME
        self.max_age = settings.SESSION_MAX_AGE

    def dumps(self, data: dict[str, Any]) -> str:
        return self.s.dumps(data)

    def loads(self, token: str) -> Optional[dict[str, Any]]:
        try:
            return self.s.loads(token)
        except BadSignature:
            return None


signer = SessionSigner()


def build_session_cookie(value: str, *, secure: bool, domain: Optional[str] = None) -> dict[str, Any]:
    settings = get_settings()
    # Cookie params for FastAPI Response.set_cookie
    return dict(
        key=settings.SESSION_COOKIE_NAME,
        value=value,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        domain=domain,
    )
