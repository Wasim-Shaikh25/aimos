"""Tests for the SaaS auth and tenant layer."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aimos.api.server import AppState, create_app
from aimos.journal.journal import Journal
from aimos.saas import db as saas_db
from aimos.saas.models import Organization, OrganizationConfig, OrganizationMember, User


@pytest.fixture(autouse=True)
def _saas_env(monkeypatch, tmp_path):
    """Enable SaaS with a temp auth DB and a fixed JWT secret."""
    monkeypatch.setenv("AIMOS__SAAS__ENABLED", "true")
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AIMOS__SAAS__JWT_SECRET", "test-secret-32-bytes-long-enough-for-hs256")
    monkeypatch.setenv("AIMOS__SAAS__REQUIRE_EMAIL_VERIFICATION", "false")
    monkeypatch.setenv("AIMOS__SAAS__REQUIRE_STRONG_PASSWORD", "false")
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
def registered_user(client):
    resp = client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "Password123!",
    })
    assert resp.status_code == 200
    return resp.json()


class TestStatus:
    def test_status_reports_saas_enabled(self, client):
        resp = client.get("/api/v2/status")
        assert resp.status_code == 200
        assert resp.json()["saas_enabled"] is True


class TestEmailAuth:
    def test_register_creates_user_and_org(self, client):
        resp = client.post("/auth/register", json={
            "email": "new@example.com",
            "password": "Password123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["organization_id"]

    def test_login_with_registered_user(self, client, registered_user):
        resp = client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "Password123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["organization_id"] == registered_user["organization_id"]

    def test_login_with_wrong_password_fails(self, client, registered_user):
        resp = client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_refresh_rotates_token(self, client, registered_user):
        refresh = registered_user["refresh_token"]
        resp = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] != registered_user["access_token"]
        assert data["refresh_token"] != refresh

    def test_logout_revokes_refresh_token(self, client, registered_user):
        refresh = registered_user["refresh_token"]
        resp = client.post("/auth/logout", json={"refresh_token": refresh})
        assert resp.status_code == 200
        resp2 = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert resp2.status_code == 401

    def test_me_requires_auth(self, client):
        resp = client.get("/api/v2/me")
        assert resp.status_code == 401

    def test_me_returns_user(self, client, registered_user):
        resp = client.get(
            "/api/v2/me",
            headers={"Authorization": f"Bearer {registered_user['access_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"


class TestOrganizations:
    def test_list_organizations(self, client, registered_user):
        token = registered_user["access_token"]
        resp = client.get("/api/v2/organizations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["role"] == "owner"

    def test_create_organization(self, client, registered_user):
        token = registered_user["access_token"]
        resp = client.post("/api/v2/organizations", params={"name": "Hedge Fund"},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Hedge Fund"
        assert data["role"] == "owner"


class TestOrgConfig:
    def test_get_and_patch_config(self, client, registered_user):
        token = registered_user["access_token"]
        org_id = registered_user["organization_id"]
        resp = client.get(
            f"/api/v2/config",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": org_id,
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {}

        resp = client.patch(
            f"/api/v2/config",
            json={"paper.max_symbols": 10},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": org_id,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["paper.max_symbols"] == 10


class TestMembers:
    def test_list_and_invite_members(self, client, registered_user):
        token = registered_user["access_token"]
        org_id = registered_user["organization_id"]

        # register a second user
        client.post("/auth/register", json={
            "email": "invitee@example.com",
            "password": "Password123!",
        })

        resp = client.get(f"/api/v2/organizations/{org_id}/members", headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
        })
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.post(f"/api/v2/organizations/{org_id}/invite", json={
            "email": "invitee@example.com",
            "role": "admin",
        }, headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = client.get(f"/api/v2/organizations/{org_id}/members", headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
        })
        assert resp.status_code == 200
        members = resp.json()
        assert any(m["email"] == "invitee@example.com" and m["role"] == "admin" for m in members)


class TestOrgScoping:
    def test_trading_endpoints_require_token_and_org(self, client, registered_user, monkeypatch):
        token = registered_user["access_token"]
        org_id = registered_user["organization_id"]
        monkeypatch.setenv("AIMOS_RUNTIME_ORG_ID", org_id)

        # No auth -> 401
        resp = client.get("/api/equity")
        assert resp.status_code == 401

        # Wrong org -> 403
        resp = client.get("/api/equity", headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": "wrong-org",
        })
        assert resp.status_code == 403

        # Correct token + org -> 200
        resp = client.get("/api/equity", headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
        })
        assert resp.status_code == 200
        assert "equity" in resp.json()


class TestPhoneAuth:
    def test_phone_send_and_verify(self, client):
        resp = client.post("/auth/phone/send", json={"phone_number": "+15551234567"})
        assert resp.status_code == 200
        # Console driver drops the message under state/smsdrop.
        code = _read_sms_drop("+15551234567")
        resp = client.post("/auth/phone/verify", json={
            "phone_number": "+15551234567",
            "code": code,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data


def _read_sms_drop(phone: str) -> str:
    import re
    from pathlib import Path
    safe = phone.replace("+", "").replace("/", "_")
    text = (Path("state") / "smsdrop" / f"{safe}.txt").read_text(encoding="utf-8")
    match = re.search(r"\d+", text)
    if not match:
        raise ValueError(f"No code found in SMS drop: {text}")
    return match.group(0)
