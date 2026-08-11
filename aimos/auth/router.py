"""Single-user auth and settings router."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from aimos.auth.security import (
    AuthError,
    FailedLoginTracker,
    LOCAL_USER,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from aimos.core.config import load_params
from aimos.settings.config import _deep_merge
from aimos.settings.settings_store import SettingsStore


auth_router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/api/v2", tags=["user"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    organization_id: str = "local"


class UserResponse(BaseModel):
    id: str
    username: str


class ExchangeKeyRequest(BaseModel):
    venue: str
    exchange_id: str | None = None
    apiKey: str
    secret: str
    testnet: bool = True
    withdraw: bool = False


class ConfigPatchRequest(BaseModel):
    overrides: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_info(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


def _admin_username() -> str:
    return os.environ.get("AIMOS_ADMIN_USERNAME", "admin")


def _admin_password() -> str:
    return os.environ.get("AIMOS_ADMIN_PASSWORD", "")


def _set_refresh_cookie(response: Response, refresh_token: str, secure: bool = False) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=30 * 86400,
        path="/",
    )


def _settings_store() -> SettingsStore:
    from aimos.core.config import load_params

    params = load_params()
    database_url = params.model_dump().get("storage", {}).get("database_url", "")
    return SettingsStore("default", database_url=database_url)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@auth_router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, response: Response):
    """Single-step login using credentials from the environment."""
    if not _admin_password():
        raise AuthError("admin password not configured")
    if req.username != _admin_username() or req.password != _admin_password():
        raise AuthError("invalid credentials")
    access = create_access_token(user_id=LOCAL_USER.id)
    refresh = create_refresh_token(user_id=LOCAL_USER.id)
    _set_refresh_cookie(response, refresh, secure=request.url.scheme == "https")
    return TokenResponse(access_token=access, user_id=LOCAL_USER.id)


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, refresh_token: str | None = None):
    """Issue a new access token from the httpOnly refresh cookie."""
    token = refresh_token or request.cookies.get("refresh_token")
    if not token:
        raise AuthError("missing refresh token")
    payload = decode_token(token, token_type="refresh")
    access = create_access_token(user_id=payload["sub"])
    refresh = create_refresh_token(user_id=payload["sub"])
    _set_refresh_cookie(response, refresh, secure=request.url.scheme == "https")
    return TokenResponse(access_token=access, user_id=payload["sub"])


@auth_router.post("/logout")
def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", path="/", httponly=True, samesite="strict")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Single-user endpoints
# ---------------------------------------------------------------------------


@user_router.get("/me", response_model=UserResponse)
def me(_user: UserResponse = Depends(get_current_user)):
    return UserResponse(id=LOCAL_USER.id, username=LOCAL_USER.username)


@user_router.get("/settings")
def get_settings(_user: UserResponse = Depends(get_current_user)) -> dict[str, Any]:
    """Return the effective configuration for the single-user dashboard.

    Secrets are never exposed; only exchange metadata (has_key, testnet, etc.).
    """
    store = _settings_store()
    overrides = store.get_config()
    base = load_params().model_dump()
    merged = _deep_merge(base, overrides)
    return {
        "mode": merged.get("mode", "paper"),
        "features": merged.get("features", {}),
        "paper": merged.get("paper", {}),
        "mandate": merged.get("mandate", {}),
        "training": merged.get("training", {}),
        "exchanges": store.get_exchanges(),
    }


@user_router.patch("/settings/config")
def patch_settings(
    req: ConfigPatchRequest,
    _user: UserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    """Update user settings. The runtime reloads these at boot."""
    return _settings_store().update_config(req.overrides)


@user_router.post("/settings/exchange")
def add_exchange(
    req: ExchangeKeyRequest,
    _user: UserResponse = Depends(get_current_user),
) -> dict[str, dict[str, Any]]:
    """Store encrypted exchange API credentials."""
    store = _settings_store()
    store.set_exchange(req.venue, req.model_dump())
    return store.get_exchanges()


@user_router.delete("/settings/exchange/{venue}")
def delete_exchange(
    venue: str,
    _user: UserResponse = Depends(get_current_user),
) -> dict[str, dict[str, Any]]:
    """Remove exchange credentials."""
    store = _settings_store()
    store.delete_exchange(venue)
    return store.get_exchanges()
