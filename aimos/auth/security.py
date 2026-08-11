"""Single-user JWT auth helpers."""

from __future__ import annotations

import base64
import os
import secrets
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from fastapi import Header, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel


class AuthError(Exception):
    """Raised for auth failures; convert to 401/403 by the router."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class _LocalUser(BaseModel):
    id: str = "local"
    username: str = "admin"


LOCAL_USER = _LocalUser()


def _secrets_dir() -> Path:
    env = os.environ.get("AIMOS_SECRETS_DIR", "")
    if env:
        return Path(env)
    return Path.home() / ".aimos" / "secrets"


def _jwt_secret_file() -> Path:
    return _secrets_dir() / ".jwt_secret"


def _load_or_create_jwt_secret() -> str:
    env = os.environ.get("AIMOS_JWT_SECRET", "").strip()
    if env:
        return env
    secret_file = _jwt_secret_file()
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    secret_file.write_text(secret, encoding="utf-8")
    try:
        import stat

        secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:  # noqa: BLE001
        pass
    return secret


def _secret() -> str:
    return _load_or_create_jwt_secret()


def create_access_token(user_id: str = "local", expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(days=7)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def create_refresh_token(user_id: str = "local", expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(days=30)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str, token_type: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("invalid token") from exc
    if payload.get("type") != token_type:
        raise AuthError(f"token type mismatch (expected {token_type})")
    return payload


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def get_current_user(authorization: str | None = Header(None)) -> _LocalUser:
    if not authorization:
        raise AuthError("Authorization required")
    if not authorization.lower().startswith("bearer "):
        raise AuthError("invalid authorization scheme")
    token = authorization[7:].strip()
    decode_token(token, token_type="access")
    return LOCAL_USER


class FailedLoginTracker:
    """Simple in-memory failed-login tracker for alerting."""

    def __init__(self, threshold: int = 3, window_seconds: float = 300.0, alert_fn=None) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.alert_fn = alert_fn
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        window = self._events.setdefault(key, deque())
        while window and window[0] < now - self.window_seconds:
            window.popleft()
        return len(window) < self.threshold

    def record(self, key: str, *, success: bool, message: str = "") -> None:
        if success:
            self._events.pop(key, None)
            return
        now = datetime.now(timezone.utc).timestamp()
        self._events.setdefault(key, deque()).append(now)
        if len(self._events[key]) >= self.threshold and self.alert_fn:
            self.alert_fn(message or f"too many failed logins for {key}")

    def clear(self, key: str) -> None:
        self._events.pop(key, None)


__all__ = ["AuthError", "LOCAL_USER", "create_access_token", "create_refresh_token", "decode_token", "get_current_user", "FailedLoginTracker"]
