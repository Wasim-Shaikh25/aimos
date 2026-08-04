"""SQLAlchemy engine, session, and base for the SaaS tenant/auth store.

The database is configured from ``saas.database_url`` (``config/saas.yaml`` or
``AIMOS__SAAS__DATABASE_URL``). Defaults to ``state/auth.sqlite``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from aimos.saas.settings import get_saas_config

log = structlog.get_logger(__name__)


def run_migrations(database_url: str | None = None) -> None:
    """Run Alembic migrations for the SaaS/auth DB.

    When ``database_url`` is omitted it is read from the SaaS config.
    """
    if database_url is None:
        database_url = get_saas_config().database_url

    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    alembic_ini = repo_root / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


class Base(DeclarativeBase):
    """Declarative base for all SaaS ORM models."""

    type_annotation_map: dict[Any, Any] = {}


_engine: Any | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """Lazy singleton engine."""
    global _engine, _SessionLocal
    if _engine is None:
        cfg = get_saas_config()
        url = cfg.database_url
        # SQLite needs check_same_thread=False when shared with FastAPI threadpool.
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        run_migrations(url)
        # Seed the single admin user when SaaS is configured.
        try:
            from aimos.saas import auth_service

            with _SessionLocal() as session:
                auth_service.ensure_admin_user(session)
        except Exception:
            # A seeding failure with SaaS enabled is a fatal misconfiguration;
            # booting without an admin would lock the operator out silently.
            log.exception("admin_seed_failed")
            raise
    return _engine


def get_session_maker():
    """Return the configured sessionmaker, creating tables on first call."""
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Session:
    """Yield a database session for FastAPI dependency injection."""
    SessionLocal = get_session_maker()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
