"""FastAPI routers for single-admin SaaS auth and settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from aimos.core.config import load_params
from aimos.saas import auth_service
from aimos.saas.config_tenant import _deep_merge
from aimos.saas.db import get_db
from aimos.saas.models import Organization, OrganizationMember, User
from aimos.saas.security import get_current_user
from aimos.saas.settings import get_saas_config
from aimos.saas.settings_store import SettingsStore

auth_router = APIRouter(prefix="/auth", tags=["auth"])
tenant_router = APIRouter(prefix="/api/v2", tags=["tenant"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    organization_id: str


class UserResponse(BaseModel):
    id: str
    email: str | None
    email_verified: bool
    phone_number: str | None
    phone_verified: bool


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


def _token_response(result: auth_service.AuthResult) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user_id=result.user.id,
        organization_id=result.organization.id if result.organization else "",
    )


# ---------------------------------------------------------------------------
# Admin login with email OTP (no public registration)
# ---------------------------------------------------------------------------


@auth_router.post("/login")
def login(req: LoginRequest, session: Session = Depends(get_db)):
    """Step 1: verify admin password and email a one-time login code."""
    auth_service.send_login_otp(session, req.email, req.password)
    return {"ok": True, "message": "Check your email for a login code."}


@auth_router.post("/login/verify", response_model=TokenResponse)
def login_verify(req: LoginVerifyRequest, session: Session = Depends(get_db)):
    """Step 2: verify the email OTP and issue tokens."""
    result = auth_service.verify_login_otp(session, req.email, req.code)
    return _token_response(result)


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, session: Session = Depends(get_db)):
    access, refresh, user_id = auth_service.refresh_access_token(session, req.refresh_token)
    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=user_id,
        organization_id=org.id if org else "",
    )


@auth_router.post("/logout")
def logout(req: RefreshRequest, session: Session = Depends(get_db)):
    auth_service.revoke_refresh_token(session, req.refresh_token)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Single-user tenant endpoints
# ---------------------------------------------------------------------------


@tenant_router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        email_verified=current_user.email_verified,
        phone_number=current_user.phone_number,
        phone_verified=current_user.phone_verified,
    )


# ---------------------------------------------------------------------------
# Single-user settings (config + encrypted exchange secrets)
# ---------------------------------------------------------------------------


def _settings_store() -> SettingsStore:
    return SettingsStore("default")


@tenant_router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
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
        "saas_enabled": get_saas_config().enabled,
    }


@tenant_router.patch("/settings/config")
def patch_settings(
    req: ConfigPatchRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update user settings.  The runtime reloads these at boot."""
    return _settings_store().update_config(req.overrides)


@tenant_router.post("/settings/exchange")
def add_exchange(
    req: ExchangeKeyRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, dict[str, Any]]:
    """Store encrypted exchange API credentials."""
    _settings_store().set_exchange(req.venue, req.model_dump())
    return _settings_store().get_exchanges()


@tenant_router.delete("/settings/exchange/{venue}")
def delete_exchange(
    venue: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, dict[str, Any]]:
    """Remove exchange credentials."""
    _settings_store().delete_exchange(venue)
    return _settings_store().get_exchanges()
