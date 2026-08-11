"""Shared SQLAlchemy engine + base for unified operational persistence.

Centralises runtime state, controls, and the model registry when
``storage.database_url`` is configured. Journal tables live in a per-tenant
schema inside the same database and are managed by ``aimos/journal/journal.py``.
SQLite is still fully supported as a fallback for dev/tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog
from sqlalchemy import JSON, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.pool import StaticPool

log = structlog.get_logger(__name__)

_SA_ENGINES: dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StorageBase(DeclarativeBase):
    pass


class RuntimeStateRecord(StorageBase):
    """Single JSON blob holding the runtime snapshot for one organization."""

    __tablename__ = "runtime_states"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ControlStateRecord(StorageBase):
    """Pause/halt/controls channel persisted across server restarts."""

    __tablename__ = "runtime_controls"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    controls: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ModelRegistryRecord(StorageBase):
    """Append-only audit trail of ML training runs."""

    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class UserSettingsRecord(StorageBase):
    """Single-row config + encrypted exchange secrets for the local user."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secrets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def normalize_sqlalchemy_url(url: str) -> str:
    """Use the psycopg v3 dialect when the URL has no explicit driver.

    SQLAlchemy 2 defaults to the psycopg2 dialect for ``postgresql://``. AIMOS
    ships psycopg (v3) via the ``[timescale]`` extra, so force the psycopg
    dialect when no driver is specified so ``storage.database_url`` just works.
    """
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if scheme in {"postgresql", "postgres"} and "+" not in scheme:
        try:
            import psycopg  # noqa: F401
            return f"postgresql+psycopg://{rest}"
        except ImportError:
            pass
    return url


def normalize_psycopg_url(url: str) -> str:
    """Strip a SQLAlchemy ``+psycopg`` driver suffix for raw ``psycopg.connect``."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}://{rest}"


def _safe_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "***", 1)
    except Exception:  # noqa: BLE001
        pass
    return url


def _sqlite_path(url: str) -> Path | None:
    if url.startswith("sqlite:///"):
        return Path(url[10:])
    return None


def get_storage_engine(database_url: str, *, echo: bool = False) -> Any:
    """Return a cached SQLAlchemy engine for the operational database."""
    normalized = normalize_sqlalchemy_url(database_url)
    if normalized in _SA_ENGINES:
        return _SA_ENGINES[normalized]

    kwargs: dict[str, Any] = {}
    if normalized.startswith("sqlite"):
        # Disable same-thread check so FastAPI threadpool readers and the loop
        # writer can share the engine on a SQLite file.
        kwargs["connect_args"] = {"check_same_thread": False}
        path = _sqlite_path(normalized)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        if ":memory:" in normalized:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(normalized, echo=echo, **kwargs)
    StorageBase.metadata.create_all(engine)
    _SA_ENGINES[normalized] = engine
    log.info("storage_engine_created", url=_safe_url(normalized), dialect=engine.dialect.name)
    return engine


def session_for(database_url: str) -> Session:
    """Return a bound Session for the given database URL."""
    return Session(get_storage_engine(database_url))


__all__ = [
    "ControlStateRecord",
    "ModelRegistryRecord",
    "RuntimeStateRecord",
    "StorageBase",
    "get_storage_engine",
    "normalize_psycopg_url",
    "normalize_sqlalchemy_url",
    "session_for",
]
