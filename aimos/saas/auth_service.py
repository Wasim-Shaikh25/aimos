"""Core authentication and registration logic for the SaaS layer."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from aimos.saas.email import send_password_reset_email, send_verification_email
from aimos.saas.models import (
    EmailVerificationCode,
    Organization,
    OrganizationMember,
    PasswordResetToken,
    PhoneVerificationCode,
    RefreshToken,
    User,
    UserIdentity,
)
from aimos.saas.oauth import (
    apple_exchange_code,
    apple_verify_id_token,
    google_exchange_code,
    google_verify_id_token,
)
from aimos.saas.security import (
    AuthError,
    create_access_token,
    create_refresh_token,
    hash_password,
    is_strong_password,
    verify_password,
)
from aimos.saas.settings import get_saas_config
from aimos.saas.sms import send_otp


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _code_expire() -> datetime:
    cfg = get_saas_config()
    return _utcnow() + timedelta(minutes=cfg.verification_code_expire_minutes)


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


def _require_strong_password(password: str) -> None:
    cfg = get_saas_config()
    if cfg.require_strong_password and not is_strong_password(password):
        raise AuthError("Password must be at least 8 characters with upper, lower, digit and symbol")


def _new_user(session: Session, email: str | None = None, phone: str | None = None) -> User:
    if not email and not phone:
        raise AuthError("Email or phone is required")
    existing_email = session.query(User).filter(User.email == email).first() if email else None
    if existing_email:
        raise AuthError("Email already registered")
    existing_phone = session.query(User).filter(User.phone_number == phone).first() if phone else None
    if existing_phone:
        raise AuthError("Phone number already registered")
    user = User(email=email, phone_number=phone)
    session.add(user)
    session.flush()
    return user


def _issue_tokens(session: Session, user: User, org: Organization) -> tuple[str, str]:
    access = create_access_token(user.id, org.id)
    refresh = create_refresh_token(session, user.id)
    return access, refresh


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------


def register_email_password(session: Session, email: str, password: str) -> AuthResult:
    """Register a new user with email + password."""
    _require_strong_password(password)
    user = _new_user(session, email=email)
    user.password_hash = hash_password(password)
    org = _create_default_organization(session, user)
    if get_saas_config().require_email_verification:
        code = _generate_code()
        session.add(EmailVerificationCode(user_id=user.id, code=hash_password(code), expires_at=_code_expire()))
        session.commit()
        send_verification_email(email, code)
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)


def verify_email(session: Session, email: str, code: str) -> User:
    """Verify an email with a 6-digit code."""
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        raise AuthError("User not found")
    record = (
        session.query(EmailVerificationCode)
        .filter(EmailVerificationCode.user_id == user.id, EmailVerificationCode.used == False)
        .order_by(EmailVerificationCode.expires_at.desc())
        .first()
    )
    if record is None or record.expires_at < _utcnow():
        raise AuthError("Code expired or not found")
    if not verify_password(code, record.code):
        raise AuthError("Invalid code")
    record.used = True
    user.email_verified = True
    session.commit()
    return user


def resend_email_verification(session: Session, email: str) -> None:
    """Resend a new email verification code."""
    user = session.query(User).filter(User.email == email).first()
    if user is None or user.email_verified:
        return
    # Invalidate old codes.
    session.query(EmailVerificationCode).filter(
        EmailVerificationCode.user_id == user.id, EmailVerificationCode.used == False
    ).update({"used": True})
    code = _generate_code()
    session.add(EmailVerificationCode(user_id=user.id, code=hash_password(code), expires_at=_code_expire()))
    session.commit()
    send_verification_email(email, code)


def login_email_password(session: Session, email: str, password: str) -> AuthResult:
    """Authenticate with email + password."""
    user = session.query(User).filter(User.email == email).first()
    if user is None or user.password_hash is None:
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    if get_saas_config().require_email_verification and not user.email_verified:
        raise AuthError("Email not verified")
    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    if org is None:
        org = _create_default_organization(session, user)
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)


def forgot_password(session: Session, email: str) -> None:
    """Send a password reset code to the user's email."""
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        return  # don't reveal whether email exists
    # Invalidate old tokens.
    session.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used == False
    ).update({"used": True})
    code = _generate_code()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_password(code),
            expires_at=_code_expire(),
        )
    )
    session.commit()
    send_password_reset_email(email, code)


def reset_password(session: Session, email: str, code: str, new_password: str) -> None:
    """Reset a password with a code."""
    _require_strong_password(new_password)
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        raise AuthError("Invalid email or code")
    record = (
        session.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > _utcnow(),
        )
        .order_by(PasswordResetToken.expires_at.desc())
        .first()
    )
    if record is None or not verify_password(code, record.token_hash):
        raise AuthError("Invalid or expired code")
    record.used = True
    user.password_hash = hash_password(new_password)
    session.commit()


# ---------------------------------------------------------------------------
# Phone OTP
# ---------------------------------------------------------------------------


def _get_user_by_phone(session: Session, phone: str) -> User | None:
    return session.query(User).filter(User.phone_number == phone).first()


def _link_or_create_phone_user(session: Session, phone: str) -> User:
    user = _get_user_by_phone(session, phone)
    if user is None:
        user = _new_user(session, phone=phone)
    return user


def send_phone_verification(session: Session, phone: str) -> None:
    """Send an OTP to a phone number (or log it in console mode)."""
    # Normalize E.164-ish.
    phone = phone.strip()
    if not phone.startswith("+"):
        raise AuthError("Phone number must start with + and country code")
    user = _get_user_by_phone(session, phone)
    if user is None:
        # Create a provisional user if not exists; they are fully created on verify.
        user = _new_user(session, phone=phone)
    # Invalidate old codes.
    session.query(PhoneVerificationCode).filter(
        PhoneVerificationCode.user_id == user.id, PhoneVerificationCode.used == False
    ).update({"used": True})
    code = _generate_code()
    session.add(
        PhoneVerificationCode(
            user_id=user.id,
            phone_number=phone,
            code=hash_password(code),
            expires_at=_code_expire(),
        )
    )
    session.commit()
    send_otp(phone, code)


def verify_phone_and_login(session: Session, phone: str, code: str) -> AuthResult:
    """Verify phone OTP and return tokens (creating a default org if needed)."""
    phone = phone.strip()
    user = _get_user_by_phone(session, phone)
    if user is None:
        raise AuthError("Phone number not found")
    record = (
        session.query(PhoneVerificationCode)
        .filter(
            PhoneVerificationCode.user_id == user.id,
            PhoneVerificationCode.phone_number == phone,
            PhoneVerificationCode.used == False,
            PhoneVerificationCode.expires_at > _utcnow(),
        )
        .order_by(PhoneVerificationCode.expires_at.desc())
        .first()
    )
    if record is None or not verify_password(code, record.code):
        raise AuthError("Invalid or expired code")
    record.used = True
    user.phone_verified = True
    session.commit()

    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    if org is None:
        org = _create_default_organization(session, user)
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)


# ---------------------------------------------------------------------------
# OAuth (Google / Apple)
# ---------------------------------------------------------------------------


def _get_or_create_identity_user(
    session: Session,
    provider: str,
    subject: str,
    email: str | None,
    name: str | None,
) -> User:
    """Find or create a user linked to an OAuth identity."""
    identity = (
        session.query(UserIdentity)
        .filter(UserIdentity.provider == provider, UserIdentity.provider_subject == subject)
        .first()
    )
    if identity:
        return identity.user

    if email:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            user = existing
            if email and not user.email:
                user.email = email
            if email and user.email == email:
                user.email_verified = True
        else:
            user = _new_user(session, email=email)
            if email:
                user.email_verified = True
    else:
        user = _new_user(session)

    session.add(
        UserIdentity(
            user_id=user.id,
            provider=provider,
            provider_subject=subject,
        )
    )
    session.commit()
    return user


def login_with_google(session: Session, code: str, redirect_uri: str | None = None) -> AuthResult:
    """Authenticate or register with a Google authorization code."""
    tokens = google_exchange_code(code, redirect_uri=redirect_uri)
    id_token = tokens.get("id_token")
    if not id_token:
        raise AuthError("Google did not return an ID token")
    claims = google_verify_id_token(id_token)
    email = claims.get("email")
    name = claims.get("name")
    subject = claims.get("sub")
    if not subject:
        raise AuthError("Google token missing subject")
    user = _get_or_create_identity_user(session, "google", subject, email, name)
    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    if org is None:
        org = _create_default_organization(session, user, name=name or "Personal")
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)


def login_with_apple(session: Session, code: str, user_payload: str | None = None, redirect_uri: str | None = None) -> AuthResult:
    """Authenticate or register with an Apple authorization code."""
    tokens = apple_exchange_code(code, redirect_uri=redirect_uri)
    id_token = tokens.get("id_token")
    if not id_token:
        raise AuthError("Apple did not return an ID token")
    claims = apple_verify_id_token(id_token)
    email = claims.get("email")
    subject = claims.get("sub")
    if not subject:
        raise AuthError("Apple token missing subject")

    name = None
    if user_payload:
        # Apple sends name JSON on first sign-in only.
        import json
        try:
            parsed = json.loads(user_payload)
            name_parts = [parsed.get("name", {}).get("firstName"), parsed.get("name", {}).get("lastName")]
            name = " ".join(p for p in name_parts if p)
        except Exception:
            pass

    user = _get_or_create_identity_user(session, "apple", subject, email, name)
    org = (
        session.query(Organization)
        .join(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .first()
    )
    if org is None:
        org = _create_default_organization(session, user, name=name or "Personal")
    access, refresh = _issue_tokens(session, user, org)
    return AuthResult(user=user, access_token=access, refresh_token=refresh, organization=org)


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
