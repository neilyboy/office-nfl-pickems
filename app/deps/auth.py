from __future__ import annotations

from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.security import signer, build_session_cookie
from app.core.config import get_settings
from app.models import User


COOKIE_SECURE = False  # can be overridden by reverse proxy/production


def get_session_data(request: Request) -> Optional[dict]:
    token = request.cookies.get(get_settings().SESSION_COOKIE_NAME)
    if not token:
        return None
    return signer.loads(token)


def get_current_user(request: Request, db: Session) -> Optional[User]:
    data = get_session_data(request)
    if not data:
        return None
    user_id = data.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def login_user(response, user: User) -> None:
    payload = {"user_id": user.id, "is_admin": user.is_admin}
    token = signer.dumps(payload)
    cookie = build_session_cookie(token, secure=COOKIE_SECURE)
    response.set_cookie(**cookie)


def logout_user(response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
