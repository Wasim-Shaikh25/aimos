"""SQLAlchemy models for AIMOS SaaS users, organizations, and tenant state.

Uses string UUIDs (36 chars) for primary keys so they are safe as filesystem
path components (per-tenant journal/state directories).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aimos.saas.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user", lazy="selectin"
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    mode: Mapped[str] = mapped_column(String(16), default="paper")  # paper | live

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", lazy="selectin"
    )
    config: Mapped["OrganizationConfig"] = relationship(
        "OrganizationConfig", back_populates="organization", uselist=False, lazy="joined"
    )
    state: Mapped["OrganizationState"] = relationship(
        "OrganizationState", back_populates="organization", uselist=False, lazy="joined"
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner/admin/member/viewer
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship("User", back_populates="memberships")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")


class EmailLoginCode(Base):
    """One-time login code sent to the admin email (2FA step)."""

    __tablename__ = "email_login_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    # Failed-guess counter so a live code is burned after too many wrong tries
    # (audit finding H3 — bounds OTP brute force).
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OrganizationConfig(Base):
    """Per-tenant config overrides (e.g. paper.max_symbols)."""

    __tablename__ = "organization_configs"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="config")


class AuthAuditLog(Base):
    """Persisted audit trail for authentication and settings lifecycle events."""

    __tablename__ = "auth_audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)


class OrganizationState(Base):
    """Per-tenant runtime state (equity, balances, positions, ladder, features, view, controls)."""

    __tablename__ = "organization_states"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    equity: Mapped[list[float]] = mapped_column(JSON, default=list)
    balances: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    positions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    broker_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sim_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ladder: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    view: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    controls: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="state")
