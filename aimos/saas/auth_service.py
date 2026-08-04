"""Core authentication logic for the SaaS layer — single admin, email OTP only.

Public registration, Google/Apple OAuth, and phone OTP were removed from the API
in the single-admin redesign (specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md
§8); this module now also drops the corresponding service-layer code so there is
no unreachable auth surface left to audit or accidentally re-expose. The only
login flow is: admin password -> email OTP -> JWT access/refresh tokens.
"""

from __future__ import annotations

import re
import secrets
import structlog
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from aimos.saas.email import send_login_code_email
from aimos.saas.models import AuthAuditLog, EmailLoginCode, Organization, OrganizationMember, RefreshToken, User
from aimos.saas.security import (
    AuthError,
    create_access_token,
    create_refresh_token,
    hash_password,
    is_strong_password,
    verify_password,
)
from aimos.saas.settings import get_saas_config

log = structlog.get_logger(__name__)

# Dummy bcrypt hash used for the login "not found" path so invalid email and
# invalid password take the same wall-clock time (REQ-18).  The plaintext is a
# throwaway; the hash itself is not a secret, only the timing is relevant.
DUMMY_PASSWORD_HASH = "$2b$12$SKrxDkdQxYIKGbaUJx0fAO8vlPgIGKiV0BgRD7/iReg5KBodUvDAS"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Max wrong OTP guesses before a live login code is burned (audit finding H3).
MAX_OTP_ATTEMPTS = 5


class FailedLoginTracker:
    """In-process counter for failed /auth/login and /auth/login/verify
    attempts.  When a configurable threshold is crossed inside the window,
    ``alert_fn`` is called with a human-readable message.  The callback is
    intentionally decoupled so ``serve.py`` can wire the Telegram sink while
    tests can stub it."""

    def __init__(
        self,
        threshold: int = 3,
        window_seconds: float = 300.0,
        alert_fn: Any | None = None,
    ) -> None:
        self.threshold = threshold
        self.window = window_seconds
        self.alert_fn = alert_fn
        self._hits: dict[str, deque[float]] = {}
        self._last_alert: dict[str, float] = {}
        self._lock = Lock()

    def record(self, key: str, success: bool, message: str = "") -> None:
        now = time.monotonic()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            if success:
                # A successful login for this key resets the failure streak.
                dq.clear()
                self._last_alert.pop(key, None)
                return
            cutoff = now - self.window
            while dq and dq[0] < cutoff:
                dq.popleft()
            dq.append(now)
            last = self._last_alert.get(key, 0.0)
            if len(dq) >= self.threshold and now - last > self.window:
                self._last_alert[key] = now
                if self.alert_fn:
                    self.alert_fn(message or f"Repeated failed login attempts for {key}")

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._last_alert.pop(key, None)


def audit_auth_event(
    session: Session,
    event: str,
    *,
    email: str | None = None,
    user_id: str | None = None,
    success: bool | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """Persist and structurally log one auth lifecycle event."""
    log.info(
        "auth_audit",
        auth_event=event,
        email=email,
        user_id=user_id,
        success=success,
        ip_address=ip_address,
        user_agent=user_agent,
        detail=detail,
    )
    try:
        session.add(
            AuthAuditLog(
                event_type=event,
                email=email,
                user_id=user_id,
                success=success,
                ip_address=ip_address,
                user_agent=user_agent,
                detail=detail,
            )
        )
        session.commit()
    except Exception:  # noqa: BLE001 — auth must never break because auditing failed
        log.exception("auth_audit_write_failed")


def _generate_code(length: int = 6) -> str:
    """Return a numeric OTP (e.g. 123456)."""
    return str(secrets.randbelow(10**length)).zfill(length)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]", "-", name.lower()).strip("-")
    return f"{base}-{uuid.uuid4().hex[:8]}"


@dataclass
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    organization: Organization


# ---------------------------------------------------------------------------
# Users and organizations
# ---------------------------------------------------------------------------


def _create_default_organization(session: Session, user: User, name: str | None = None) -> Organization:
    """Create a default personal organization and owner membership for a user."""
    cfg = get_saas_config()
    org_name = name or cfg.tenant.default_org_name or "Personal"
    org = Organization(
        name=org_name,
        slug=_slugify(org_name),
        owner_id=user.id,
    )
    session.add(org)
    session.flush()
    member = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    session.add(member)
    session.commit()
    return org


def _issue_tokens(session: Session, user: User, org: Organization) -> tuple[str, str]:
    access = create_access_token(user.id, org.id)
    refresh = create_refresh_token(session, user.id)
    return access, refresh


# ---------------------------------------------------------------------------
# Refresh / logout
# ---------------------------------------------------------------------------


def refresh_access_token(session: Session, refresh_token: str) -> tuple[str, str, str]:
    """Rotate refresh token and return (new_access, new_refresh, user_id)."""
    from aimos.saas.security import decode_token

    payload = decode_token(refresh_token, token_type="refresh")
    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid refresh token")

    # Find a non-revoked matching token hash.
    candidates = session.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > _utcnow(),
    ).all()
    match = next((t for t in candidates if verify_password(refresh_token, t.token_hash)), None)
    if match is None:
        raise AuthError("Invalid or expired refresh token")

    # Revoke the old token and issue a new pair.
    match.revoked_at = _utcnow()
    session.commit()

    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    org_id = org.id if org else None
    new_access = create_access_token(user_id, org_id)
    new_refresh = create_refresh_token(session, user_id)
    return new_access, new_refresh, user_id


def revoke_refresh_token(session: Session, refresh_token: str) -> None:
    """Logout: revoke the refresh token."""
    from aimos.saas.security import decode_token

    payload = decode_token(refresh_token, token_type="refresh")
    user_id = payload.get("sub")
    if not user_id:
        return
    candidates = session.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    ).all()
    for t in candidates:
        if verify_password(refresh_token, t.token_hash):
            t.revoked_at = _utcnow()
    session.commit()


# ---------------------------------------------------------------------------
# Single admin user + email OTP login
# ---------------------------------------------------------------------------


def ensure_admin_user(session: Session) -> User | None:
    """Seed the single admin user from SaaS config when it is enabled.

    No public registration is exposed; the operator provides credentials in
    ``config/saas.yaml`` or via ``AIMOS__SAAS__ADMIN__*`` env vars.  The
    plaintext password is hashed on first run and is never logged or returned.
    """
    cfg = get_saas_config()
    if not cfg.enabled or not cfg.admin.email or not cfg.admin.password:
        return None
    user = session.query(User).filter(User.email == cfg.admin.email).first()
    if user is None:
        user = User(
            id=cfg.admin.user_id,
            email=cfg.admin.email,
            phone_number=cfg.admin.phone or None,
            email_verified=True,
            password_hash=hash_password(cfg.admin.password),
        )
        session.add(user)
        session.flush()
    # NOTE: do NOT re-hash the existing admin password on every boot.  The
    # password is now changed through the /api/v2/me/password endpoint so
    # config edits do not silently revert an out-of-band change (REQ-4).
    # Ensure a fallback organization exists for routes that still expect one.
    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .first()
    )
    if org is None:
        org = Organization(
            name=cfg.tenant.default_org_name or "Personal",
            slug=f"admin-{uuid.uuid4().hex[:8]}",
            owner_id=user.id,
        )
        session.add(org)
        session.flush()
        session.add(OrganizationMember(user_id=user.id, organization_id=org.id, role="owner"))
    session.commit()
    return user


def change_admin_password(session: Session, user: User, current_password: str, new_password: str) -> None:
    """Change the admin password and revoke all outstanding refresh tokens."""
    if user.password_hash is None or not verify_password(current_password, user.password_hash):
        raise AuthError("Invalid current password")
    if not is_strong_password(new_password):
        raise HTTPException(status_code=400, detail="New password does not meet strength requirements")
    user.password_hash = hash_password(new_password)
    session.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": _utcnow()})
    session.commit()


def _otp_expire() -> datetime:
    return _utcnow() + timedelta(minutes=get_saas_config().otp_expire_minutes)


def send_login_otp(session: Session, email: str, password: str) -> str:
    """Verify the admin password and email a one-time login code.

    Returns the code for local/test use; production callers should only use it
    to display the dev-drop path.  The code is never logged by default.
    """
    user = session.query(User).filter(User.email == email).first()
    if user is None or user.password_hash is None:
        # Dummy bcrypt comparison keeps the timing of "not found" indistinguishable
        # from "wrong password" (REQ-18).
        verify_password(password, DUMMY_PASSWORD_HASH)
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    # Invalidate old codes.
    session.query(EmailLoginCode).filter(
        EmailLoginCode.user_id == user.id, EmailLoginCode.used == False
    ).update({"used": True})
    code = _generate_code()
    session.add(
        EmailLoginCode(
            user_id=user.id,
            code_hash=hash_password(code),
            expires_at=_otp_expire(),
        )
    )
    session.commit()
    send_login_code_email(email, code)
    return code


def verify_login_otp(session: Session, email: str, code: str) -> AuthResult:
    """Verify a login OTP and issue tokens for the single admin user.

    A live code is burned after ``MAX_OTP_ATTEMPTS`` wrong guesses so the 6-digit
    space cannot be brute-forced within a code window (audit finding H3).
    """
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        raise AuthError("Invalid email or code")
    record = (
        session.query(EmailLoginCode)
        .filter(
            EmailLoginCode.user_id == user.id,
            EmailLoginCode.used == False,
            EmailLoginCode.expires_at > _utcnow(),
        )
        .order_by(EmailLoginCode.expires_at.desc())
        .first()
    )
    if record is None:
        raise AuthError("Invalid or expired code")
    if record.attempts >= MAX_OTP_ATTEMPTS:
        record.used = True  # burn it: operator must request a fresh code
        session.commit()
        raise AuthError("Too many attempts — request a new code")
    if not verify_password(code, record.code_hash):
        record.attempts += 1
        session.commit()
        raise AuthError("Invalid or expired code")
    record.used = True
    session.commit()

    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)
