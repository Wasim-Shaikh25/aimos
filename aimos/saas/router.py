"""FastAPI routers for SaaS auth and tenant management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from aimos.saas import auth_service
from aimos.saas.db import get_db
from aimos.saas.models import Organization, OrganizationConfig, OrganizationMember, User
from aimos.saas.oauth import (
    apple_authorize_url,
    generate_nonce,
    generate_state,
    google_authorize_url,
)
from aimos.saas.security import (
    AuthError,
    TenantContext,
    create_access_token,
    get_current_user,
    get_tenant_context,
    require_role,
)
from aimos.saas.settings import get_saas_config

auth_router = APIRouter(prefix="/auth", tags=["auth"])
tenant_router = APIRouter(prefix="/api/v2", tags=["tenant"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class PhoneSendRequest(BaseModel):
    phone_number: str


class PhoneVerifyRequest(BaseModel):
    phone_number: str
    code: str


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


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str
    mode: str


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _absolute_redirect(request: Request, configured: str) -> str:
    """Convert a configured redirect path into an absolute URL."""
    if configured.startswith("http://") or configured.startswith("https://"):
        return configured
    base = str(request.base_url).rstrip("/")
    return base + (configured if configured.startswith("/") else "/" + configured)


def _token_response(result: auth_service.AuthResult) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user_id=result.user.id,
        organization_id=result.organization.id,
    )


# ---------------------------------------------------------------------------
# Email + password auth
# ---------------------------------------------------------------------------


@auth_router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, session: Session = Depends(get_db)):
    result = auth_service.register_email_password(session, req.email, req.password)
    return _token_response(result)


@auth_router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, session: Session = Depends(get_db)):
    result = auth_service.login_email_password(session, req.email, req.password)
    return _token_response(result)


@auth_router.post("/verify-email")
def verify_email(req: VerifyEmailRequest, session: Session = Depends(get_db)):
    user = auth_service.verify_email(session, req.email, req.code)
    return {"ok": True, "email_verified": user.email_verified}


@auth_router.post("/resend-verification")
def resend_verification(req: ResendVerificationRequest, session: Session = Depends(get_db)):
    auth_service.resend_email_verification(session, req.email)
    return {"ok": True}


@auth_router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, session: Session = Depends(get_db)):
    auth_service.forgot_password(session, req.email)
    return {"ok": True}


@auth_router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, session: Session = Depends(get_db)):
    auth_service.reset_password(session, req.email, req.code, req.new_password)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Token refresh / logout
# ---------------------------------------------------------------------------


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, session: Session = Depends(get_db)):
    access, refresh, user_id = auth_service.refresh_access_token(session, req.refresh_token)
    # Find default org for response.
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
# OAuth2
# ---------------------------------------------------------------------------


@auth_router.get("/google")
def google_auth(request: Request):
    cfg = get_saas_config().oauth.google
    if not cfg.client_id:
        raise AuthError("Google OAuth is not configured")
    redirect_uri = _absolute_redirect(request, cfg.redirect_uri)
    return {
        "authorization_url": google_authorize_url(
            state=generate_state(),
            nonce=generate_nonce(),
            redirect_uri=redirect_uri,
        ),
    }


@auth_router.get("/google/callback")
def google_callback(request: Request, code: str = Query(...), session: Session = Depends(get_db)):
    cfg = get_saas_config().oauth.google
    redirect_uri = _absolute_redirect(request, cfg.redirect_uri)
    result = auth_service.login_with_google(session, code, redirect_uri=redirect_uri)
    return _token_response(result)


@auth_router.get("/apple")
def apple_auth(request: Request):
    cfg = get_saas_config().oauth.apple
    if not cfg.client_id:
        raise AuthError("Apple Sign In is not configured")
    redirect_uri = _absolute_redirect(request, cfg.redirect_uri)
    return {
        "authorization_url": apple_authorize_url(
            state=generate_state(),
            nonce=generate_nonce(),
            redirect_uri=redirect_uri,
        ),
    }


@auth_router.post("/apple/callback")
def apple_callback(
    request: Request,
    code: str = Form(...),
    user: str | None = Form(None),
    session: Session = Depends(get_db),
):
    cfg = get_saas_config().oauth.apple
    redirect_uri = _absolute_redirect(request, cfg.redirect_uri)
    result = auth_service.login_with_apple(session, code, user_payload=user, redirect_uri=redirect_uri)
    return _token_response(result)


# ---------------------------------------------------------------------------
# Phone auth
# ---------------------------------------------------------------------------


@auth_router.post("/phone/send")
def phone_send(req: PhoneSendRequest, session: Session = Depends(get_db)):
    auth_service.send_phone_verification(session, req.phone_number)
    return {"ok": True}


@auth_router.post("/phone/verify", response_model=TokenResponse)
def phone_verify(req: PhoneVerifyRequest, session: Session = Depends(get_db)):
    result = auth_service.verify_phone_and_login(session, req.phone_number, req.code)
    return _token_response(result)


# ---------------------------------------------------------------------------
# Tenant management
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


@tenant_router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    rows = (
        session.query(Organization, OrganizationMember.role)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == current_user.id)
        .order_by(Organization.created_at.asc())
        .all()
    )
    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            role=role,
            mode=org.mode,
        )
        for org, role in rows
    ]


@tenant_router.post("/organizations", response_model=OrganizationResponse)
def create_organization(
    name: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    from aimos.saas.auth_service import _create_default_organization, _slugify

    org = Organization(name=name, slug=_slugify(name), owner_id=current_user.id)
    session.add(org)
    session.flush()
    session.add(OrganizationMember(user_id=current_user.id, organization_id=org.id, role="owner"))
    session.commit()
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        role="owner",
        mode=org.mode,
    )


@tenant_router.post("/organizations/{org_id}/invite")
def invite_member(
    org_id: str,
    req: InviteRequest,
    ctx: TenantContext = Depends(require_role({"owner", "admin"})),
    session: Session = Depends(get_db),
):
    # Placeholder: in production this would send an email invite and create a
    # pending membership. For now we create the membership directly if a user
    # with that email exists.
    invitee = session.query(User).filter(User.email == req.email).first()
    if invitee is None:
        return {"ok": False, "error": "User not found; invite by email not yet implemented"}
    existing = (
        session.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == invitee.id,
            OrganizationMember.organization_id == org_id,
        )
        .first()
    )
    if existing:
        return {"ok": False, "error": "User is already a member"}
    session.add(
        OrganizationMember(
            user_id=invitee.id,
            organization_id=org_id,
            role=req.role,
        )
    )
    session.commit()
    return {"ok": True, "user_id": invitee.id, "role": req.role}


@tenant_router.get("/organizations/{org_id}/members")
def list_members(
    org_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_db),
):
    members = (
        session.query(User, OrganizationMember.role)
        .join(OrganizationMember)
        .filter(OrganizationMember.organization_id == org_id)
        .order_by(OrganizationMember.joined_at.asc())
        .all()
    )
    return [
        {"user_id": user.id, "email": user.email, "phone": user.phone_number, "role": role}
        for user, role in members
    ]


@tenant_router.get("/config")
def get_org_config(
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_db),
):
    cfg = session.query(OrganizationConfig).filter(
        OrganizationConfig.organization_id == ctx.organization.id
    ).first()
    return cfg.overrides if cfg else {}


@tenant_router.patch("/config")
def patch_org_config(
    overrides: dict[str, Any],
    ctx: TenantContext = Depends(require_role({"owner", "admin"})),
    session: Session = Depends(get_db),
):
    cfg = session.query(OrganizationConfig).filter(
        OrganizationConfig.organization_id == ctx.organization.id
    ).first()
    if cfg is None:
        cfg = OrganizationConfig(organization_id=ctx.organization.id, overrides={})
        session.add(cfg)
    cfg.overrides.update(overrides)
    session.commit()
    return cfg.overrides


# ---------------------------------------------------------------------------
# Cookie helpers for SPA
# ---------------------------------------------------------------------------


def set_auth_cookies(response: Any, access_token: str, refresh_token: str) -> None:
    """Attach secure cookies to a response (used by dashboard SPA callbacks)."""
    response.set_cookie("access_token", access_token, httponly=True, samesite="lax")
    response.set_cookie("refresh_token", refresh_token, httponly=True, samesite="lax")
