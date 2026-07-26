"""SaaS migration: single-user → default tenant."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from aimos.saas.security import verify_password


def _load_migration():
    spec = importlib.util.spec_from_file_location("migrate_to_saas", Path(__file__).resolve().parents[1] / "scripts" / "migrate_to_saas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migrate(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{db}")

    journal = tmp_path / "aimos.sqlite"
    journal.write_bytes(b"sqlite3")
    state_dir = tmp_path / "state"

    from aimos.saas import db as db_mod
    db_mod._engine = None
    db_mod._SessionLocal = None

    migration = _load_migration()
    return migration.main([
        "--org-id", "testorg",
        "--admin-email", "admin@test.com",
        "--admin-password", "Password123!",
        "--state-dir", str(state_dir),
        "--journal", str(journal),
    ])


def test_migrate_creates_tenant_and_user(tmp_path, monkeypatch):
    assert _run_migrate(tmp_path, monkeypatch) == 0

    from aimos.saas.db import get_session_maker
    session = get_session_maker()()
    from aimos.saas.models import Organization, OrganizationMember, User
    org = session.get(Organization, "testorg")
    assert org is not None
    assert org.name == "Default"
    user = session.query(User).filter(User.email == "admin@test.com").first()
    assert user is not None
    assert verify_password("Password123!", user.password_hash)
    member = session.query(OrganizationMember).filter(
        OrganizationMember.organization_id == "testorg",
        OrganizationMember.user_id == user.id,
    ).first()
    assert member is not None
    assert member.role == "owner"
    session.close()

    new_journal = tmp_path / "state" / "journals" / "testorg.sqlite"
    assert new_journal.exists()
    assert new_journal.read_bytes() == b"sqlite3"
