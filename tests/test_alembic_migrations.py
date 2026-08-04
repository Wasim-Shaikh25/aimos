"""Alembic migration coverage for the SaaS/auth DB."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from aimos.saas.db import run_migrations


def _table_cols(path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        return {c["name"] for c in inspect(conn).get_columns("email_login_codes")}


@pytest.mark.parametrize("downgrade_first", [False, True])
def test_migrations_create_attempts_column(tmp_path, downgrade_first):
    db = tmp_path / "auth.db"
    url = f"sqlite:///{db}"

    run_migrations(url)
    assert "attempts" in _table_cols(db)

    if downgrade_first:
        from alembic import command
        from alembic.config import Config

        repo_root = Path(__file__).resolve().parents[1]
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.downgrade(cfg, "-1")
        assert "attempts" not in _table_cols(db)
        command.upgrade(cfg, "head")
        assert "attempts" in _table_cols(db)
