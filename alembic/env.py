"""Alembic environment for the AIMOS SaaS/auth database.

The target metadata is ``aimos.saas.models.Base``.  The SQLAlchemy URL is
read from ``AIMOS__SAAS__DATABASE_URL`` (highest priority), then falls back to
``config/saas.yaml`` / ``AIMOS__SAAS__*`` env overrides.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Load the SaaS models so autogenerate has something to compare.
# ``settings_store`` registers the ``user_settings`` table on the same ``Base``.
from aimos.saas import settings_store  # noqa: E402,F401
from aimos.saas.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    env_url = os.environ.get("AIMOS__SAAS__DATABASE_URL")
    if env_url:
        return env_url
    # Import lazily so env.py can be imported without a full config tree when
    # the operator sets the env var explicitly.
    from aimos.saas.settings import get_saas_config

    return get_saas_config().database_url


_PLACEHOLDER = "driver://user:pass@localhost/dbname"


def _set_url() -> None:
    # Allow callers (e.g. the runtime get_engine()) to pin the URL by setting
    # it on the Config object before invoking Alembic.
    url = config.get_main_option("sqlalchemy.url")
    if not url or url == _PLACEHOLDER:
        url = _resolve_database_url()
    if url.startswith("sqlite"):
        # Ensure the parent directory exists for file-based SQLite so Alembic
        # can create the database file on first migration.
        from pathlib import Path

        path = url.replace("sqlite:///", "")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    _set_url()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _set_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
