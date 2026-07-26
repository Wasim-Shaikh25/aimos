"""Password hashing, JWT handling, and FastAPI auth/tenant dependencies."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from aimos.saas.db import get_db
from aimos.saas.models import Organization, OrganizationMember, RefreshToken, User
from aimos.saas.settings import get_saas_config


http_bearer = HTTPBearer(auto_error=False)


class AuthError(HTTPException):
    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class PermissionError(HTTPException):
    def __init__(self, detail: str = "Permission denied") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def is_strong_password(password: str) -> bool:
    """Minimum 8 chars, upper, lower, digit, symbol."""
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[^A-Za-z0-9]", password):
        return False
    return True


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, org_id: str | None = None) -> str:
    """Issue a short-lived access token with a unique JWT ID."""
    cfg = get_saas_config()
    now = _utcnow()
    expire = now + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "access",
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")


def create_refresh_token(session: Session, user_id: str) -> str:
    """Issue a long-lived refresh token with a unique JWT ID and persist its hash."""
    cfg = get_saas_config()
    now = _utcnow()
    plain = jwt.encode(
        {
            "sub": user_id,
            "type": "refresh",
            "jti": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + timedelta(days=cfg.refresh_token_expire_days),
        },
        cfg.jwt_secret,
        algorithm="HS256",
    )
    token_hash = hash_password(plain)
    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=_utcnow() + timedelta(days=cfg.refresh_token_expire_days),
    )
    session.add(rt)
    session.commit()
    return plain


def decode_token(token: str, token_type: str | None = None) -> dict[str, Any]:
    """Decode a JWT and optionally enforce the ``type`` claim."""
    cfg = get_saas_config()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc
    if token_type and payload.get("type") != token_type:
        raise AuthError("Wrong token type")
    return payload


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    """Read token from Authorization header or secure cookie."""
    if credentials:
        return credentials.credentials
    token = request.cookies.get("access_token")
    if token:
        return token
    raise AuthError("Missing access token")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    session: Session = Depends(get_db),
) -> User:
    """Return the authenticated user or raise 401."""
    token = _extract_token(request, credentials)
    payload = decode_token(token, token_type="access")
    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise AuthError("Invalid token payload")
    user = session.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AuthError("User not found")
    cfg = get_saas_config()
    if cfg.require_email_verification and not user.email_verified:
        raise AuthError("Email not verified")
    return user


@dataclass
class TenantContext:
    """Resolved tenant scope for a request."""

    user: User
    organization: Organization
    membership: OrganizationMember
    session: Session


def get_tenant_context(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> TenantContext:
    """Resolve the active organization from the ``X-Organization-Id`` header."""
    org_id = request.headers.get("X-Organization-Id") or request.cookies.get("active_org")
    if not org_id:
        # Fall back to the user's first owned organization.
        membership = (
            session.query(OrganizationMember)
            .filter(OrganizationMember.user_id == current_user.id)
            .order_by(OrganizationMember.joined_at.asc())
            .first()
        )
        if membership:
            org_id = membership.organization_id
    if not org_id:
        raise PermissionError("No organization selected")

    membership = (
        session.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.organization_id == org_id,
        )
        .first()
    )
    if membership is None:
        raise PermissionError("Organization access denied")

    organization = session.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise PermissionError("Organization not found")

    return TenantContext(
        user=current_user,
        organization=organization,
        membership=membership,
        session=session,
    )


def require_role(allowed: set[str]):
    """Factory for a dependency that enforces organization role."""
    def checker(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if ctx.membership.role not in allowed:
            raise PermissionError("Insufficient organization role")
        return ctx
    return checker
