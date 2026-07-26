"""Tests for the single-admin SaaS auth and settings layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aimos.api.server import AppState, create_app
from aimos.journal.journal import Journal
from aimos.saas import db as saas_db


@pytest.fixture(autouse=True)
def _saas_env(monkeypatch, tmp_path):
    """Enable SaaS with a temp auth DB, fixed JWT secret, and a seeded admin."""
    monkeypatch.setenv("AIMOS__SAAS__ENABLED", "true")
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AIMOS__SAAS__JWT_SECRET", "test-secret-32-bytes-long-enough-for-hs256")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__EMAIL", "admin@example.com")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__PASSWORD", "AdminPass123!")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__USER_ID", "admin-test")
    # Reset the singleton engine so every test gets a fresh database.
    saas_db._engine = None
    saas_db._SessionLocal = None
    yield
    saas_db._engine = None
    saas_db._SessionLocal = None


@pytest.fixture
def client():
    state = AppState(journal=Journal(":memory:"))
    app = create_app(state)
    return TestClient(app)


@pytest.fixture
def admin_tokens(client, monkeypatch):
    # Request login code.
    resp = client.post("/auth/login", json={
        "email": "admin@example.com",
        "password": "AdminPass123!",
    })
    assert resp.status_code == 200
    # Read the dev-drop code (SMTP is not configured in tests).
    code = (Path("state") / "maildrop" / "login-admin@example.com.txt").read_text(encoding="utf-8")
    resp = client.post("/auth/login/verify", json={
        "email": "admin@example.com",
        "code": code,
    })
    assert resp.status_code == 200
    return resp.json()


class TestStatus:
    def test_status_reports_saas_enabled(self, client):
        resp = client.get("/api/v2/status")
        assert resp.status_code == 200
        assert resp.json()["saas_enabled"] is True


class TestAdminLogin:
    def test_login_sends_otp(self, client):
        resp = client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "AdminPass123!",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert (Path("state") / "maildrop" / "login-admin@example.com.txt").exists()

    def test_login_wrong_password_fails(self, client):
        resp = client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_verify_login_issues_tokens(self, client):
        client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "AdminPass123!",
        })
        code = (Path("state") / "maildrop" / "login-admin@example.com.txt").read_text(encoding="utf-8")
        resp = client.post("/auth/login/verify", json={
            "email": "admin@example.com",
            "code": code,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user_id"] == "admin-test"

    def test_me_requires_auth(self, client):
        resp = client.get("/api/v2/me")
        assert resp.status_code == 401

    def test_me_returns_user(self, client, admin_tokens):
        resp = client.get("/api/v2/me", headers={
            "Authorization": f"Bearer {admin_tokens['access_token']}",
        })
        assert resp.status_code == 200
        assert resp.json()["email"] == "admin@example.com"

    def test_refresh_rotates_token(self, client, admin_tokens):
        refresh = admin_tokens["refresh_token"]
        resp = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] != admin_tokens["access_token"]
        assert data["refresh_token"] != refresh

    def test_logout_revokes_refresh_token(self, client, admin_tokens):
        refresh = admin_tokens["refresh_token"]
        resp = client.post("/auth/logout", json={"refresh_token": refresh})
        assert resp.status_code == 200
        resp2 = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert resp2.status_code == 401


class TestSettings:
    def test_get_settings(self, client, admin_tokens):
        resp = client.get("/api/v2/settings", headers={
            "Authorization": f"Bearer {admin_tokens['access_token']}",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "exchanges" in data
        assert data["saas_enabled"] is True

    def test_patch_config(self, client, admin_tokens):
        token = admin_tokens["access_token"]
        resp = client.patch("/api/v2/settings/config", json={
            "overrides": {"paper": {"max_symbols": 7}},
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["paper"]["max_symbols"] == 7

    def test_exchange_keys_encrypted(self, client, admin_tokens):
        token = admin_tokens["access_token"]
        resp = client.post("/api/v2/settings/exchange", json={
            "venue": "binance",
            "exchange_id": "binance",
            "apiKey": "abc",
            "secret": "def",
            "testnet": True,
            "withdraw": False,
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["binance"]["has_key"] is True
        assert "apiKey" not in data["binance"]

    def test_delete_exchange(self, client, admin_tokens):
        token = admin_tokens["access_token"]
        client.post("/api/v2/settings/exchange", json={
            "venue": "binance",
            "apiKey": "x",
            "secret": "y",
        }, headers={"Authorization": f"Bearer {token}"})
        resp = client.delete("/api/v2/settings/exchange/binance", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert "binance" not in resp.json()


class TestOrgScoping:
    def test_trading_endpoints_require_token(self, client, admin_tokens, monkeypatch):
        token = admin_tokens["access_token"]
        org_id = admin_tokens["organization_id"]
        monkeypatch.setenv("AIMOS_RUNTIME_ORG_ID", org_id)

        resp = client.get("/api/equity")
        assert resp.status_code == 401

        resp = client.get("/api/equity", headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
        })
        assert resp.status_code == 200
        assert "equity" in resp.json()
