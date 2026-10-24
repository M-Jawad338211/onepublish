"""Single-admin auth: an argon2-checked password and a signed, httpOnly session cookie."""

import time
from collections import defaultdict, deque
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session

COOKIE = "op_session"
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_hasher = PasswordHasher()


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if not settings.session_secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SESSION_SECRET is not set")
    return URLSafeTimedSerializer(settings.session_secret, salt="op-session")


def verify_password(settings: Settings, password: str) -> bool:
    if not settings.admin_password_hash:
        return False
    try:
        return _hasher.verify(settings.admin_password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE,
        _serializer(settings).dumps({"u": "admin"}),
        max_age=settings.session_max_age_s,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def is_authenticated(request: Request, settings: Settings) -> bool:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return False
    try:
        _serializer(settings).loads(raw, max_age=settings.session_max_age_s)
    except BadSignature:
        return False
    return True


def require_admin(request: Request, settings: SettingsDep) -> None:
    if not is_authenticated(request, settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")


class LoginLimiter:
    """5 failed attempts per client per 15 min."""

    def __init__(self, limit: int = 5, window_s: float = 900):
        self.limit = limit
        self.window_s = window_s
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._fails[key]
        now = time.monotonic()
        while q and now - q[0] > self.window_s:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def fail(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_limiter = LoginLimiter()


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
