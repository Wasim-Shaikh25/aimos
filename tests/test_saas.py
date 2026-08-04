"""Tests for the single-admin SaaS auth and settings layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aimos.api.server import AppState, create_app
from aimos.journal.journal import Journal
from aimos.saas import db as saas_db
from aimos.saas.models import AuthAuditLog


@pytest.fixture(autouse=True)
def _saas_env(monkeypatch, tmp_path):
    """Enable SaaS with a temp auth DB, fixed JWT secret, and a seeded admin."""
    monkeypatch.setenv("AIMOS__SAAS__ENABLED", "true")
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AIMOS__SAAS__JWT_SECRET", "test-secret-32-bytes-long-enough-for-hs256")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__EMAIL", "admin@example.com")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__PASSWORD", "AdminPass123!")
    monkeypatch.setenv("AIMOS__SAAS__ADMIN__USER_ID", "admin-test")
    monkeypatch.setenv("AIMOS_SECRETS_DIR", str(tmp_path / "secrets"))
    # Dev maildrop is opt-in since finding H2; tests read login codes from it.
    monkeypatch.setenv("AIMOS_DEV_MAILDROP", "1")
    # Reset the singleton engine and settings key cache so every test is isolated.
    saas_db._engine = None
    saas_db._SessionLocal = None
    from aimos.saas.settings_store import SettingsStore

    SettingsStore._key = None
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
        body = resp.json()
        assert body["saas_enabled"] is True
        assert "features" in body
        assert "halted" in body
        assert body["halted"] is False


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

    def test_login_unknown_email_fails_without_leak(self, client):
        """REQ-18: unknown email returns 401 indistinguishable from wrong password."""
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "AdminPass123!",
        })
        assert resp.status_code == 401
        assert "ok" not in resp.json()

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
        assert "refresh_token" not in data
        assert data["user_id"] == "admin-test"
        # Refresh token is returned in an httpOnly cookie.
        set_cookie = resp.headers.get("set-cookie", "")
        assert "refresh_token" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie or "SameSite=Strict" in set_cookie

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
        # The fixture left the refresh token in the httpOnly cookie.
        resp = client.post("/auth/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] != admin_tokens["access_token"]
        assert "refresh_token" not in data
        assert "refresh_token" in resp.headers.get("set-cookie", "")

    def test_logout_revokes_refresh_token(self, client, admin_tokens):
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        # The clear-cookie directive matches the set-cookie attributes.
        set_cookie = resp.headers.get("set-cookie", "")
        assert "refresh_token=\"\"" in set_cookie or "Max-Age=0" in set_cookie or "expires=Thu" in set_cookie
        assert "SameSite=strict" in set_cookie or "SameSite=Strict" in set_cookie
        # After logout the httpOnly cookie is cleared and the refresh token is revoked.
        resp2 = client.post("/auth/refresh")
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


class TestSpaReachableWhenSaasEnabled:
    """Audit finding C2: enabling SaaS must NOT lock out the static SPA shell,
    or there is no way to reach the login page. But the trading API stays gated."""

    def _spa_app(self, tmp_path, monkeypatch):
        # Build the full app (with the SPA mount) pointing at a temp dist dir.
        import aimos.runtime.serve as serve
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
        (dist / "assets" / "app.js").write_text("console.log('spa')")
        monkeypatch.setattr(serve, "DIST", dist)
        app = serve.build_app(offline=True)
        return TestClient(app)

    def test_spa_index_reachable(self, tmp_path, monkeypatch):
        c = self._spa_app(tmp_path, monkeypatch)  # no lifespan → no bg loop
        r = c.get("/")
        assert r.status_code == 200 and 'id="root"' in r.text

    def test_spa_assets_reachable(self, tmp_path, monkeypatch):
        c = self._spa_app(tmp_path, monkeypatch)
        assert c.get("/assets/app.js").status_code == 200

    def test_spa_client_route_reachable(self, tmp_path, monkeypatch):
        c = self._spa_app(tmp_path, monkeypatch)
        assert c.get("/positions").status_code == 200  # SPA deep-link

    def test_api_still_requires_token(self, tmp_path, monkeypatch):
        c = self._spa_app(tmp_path, monkeypatch)
        assert c.get("/api/decisions").status_code == 401  # not over-broadly exempt

    def test_metrics_still_protected(self, tmp_path, monkeypatch):
        c = self._spa_app(tmp_path, monkeypatch)
        assert c.get("/metrics").status_code == 401


class TestSpaTraversalBlocked:
    """Audit finding C1: the SPA catch-all must not serve files outside dist."""

    def _app(self, tmp_path, monkeypatch):
        import aimos.runtime.serve as serve
        dist = tmp_path / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
        # a secret sibling of dist, mimicking state/.jwt_secret
        (tmp_path / "secret.txt").write_text("TOP-SECRET-VALUE")
        monkeypatch.setattr(serve, "DIST", dist)
        return TestClient(serve.build_app(offline=True)), tmp_path

    def test_encoded_traversal_returns_spa_not_secret(self, tmp_path, monkeypatch):
        c, _ = self._app(tmp_path, monkeypatch)
        for attack in (
            "/%2e%2e%2fsecret.txt",
            "/%2e%2e%2f%2e%2e%2fsecret.txt",
            "/..%2fsecret.txt",
            "/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ):
            r = c.get(attack)
            assert "TOP-SECRET-VALUE" not in r.text
            assert "root:" not in r.text


class TestOtpNotLeaked:
    """Audit finding H2: login codes are not written to disk or logged by default."""

    def test_maildrop_not_written_without_dev_flag(self, client, monkeypatch):
        monkeypatch.delenv("AIMOS_DEV_MAILDROP", raising=False)
        drop = Path("state") / "maildrop" / "login-admin@example.com.txt"
        if drop.exists():
            drop.unlink()  # clear any leftover from another test sharing state/
        r = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
        assert r.status_code == 200
        assert not drop.exists()  # this login must not (re)create it

    def test_code_not_in_log_body(self, client, monkeypatch):
        monkeypatch.delenv("AIMOS_DEV_MAILDROP", raising=False)
        import aimos.saas.email as email_mod
        captured = {}
        orig = email_mod.log.warning

        def _spy(event, **kw):
            captured["event"] = event
            captured["kw"] = kw
            return orig(event, **kw)

        monkeypatch.setattr(email_mod.log, "warning", _spy)
        # Trigger the no-SMTP warning path.
        email_mod.send_login_code_email("admin@example.com", "424242")
        # The warning must NOT carry the code in any field.
        assert "body" not in captured.get("kw", {})
        assert "424242" not in repr(captured.get("kw", {}))


class TestOtpBruteForceBounded:
    """Audit finding H3: a live login code is burned after MAX_OTP_ATTEMPTS."""

    def test_code_burned_after_max_attempts(self, client):
        from aimos.saas import auth_service
        client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
        code = (Path("state") / "maildrop" / "login-admin@example.com.txt").read_text().strip()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(auth_service.MAX_OTP_ATTEMPTS):
            r = client.post("/auth/login/verify", json={"email": "admin@example.com", "code": wrong})
            assert r.status_code == 401
        # Even the CORRECT code is now rejected — the code was burned.
        r = client.post("/auth/login/verify", json={"email": "admin@example.com", "code": code})
        assert r.status_code == 401


class TestAuthThrottle:
    """Audit finding H3: the /auth/* endpoints are rate-limited per client."""

    def test_login_throttled_after_window_cap(self, client):
        from aimos.api import server
        seen_429 = False
        for _ in range(server._AUTH_MAX_PER_WINDOW + 5):
            r = client.post("/auth/login", json={"email": "admin@example.com", "password": "x"})
            if r.status_code == 429:
                seen_429 = True
                break
        assert seen_429


class TestControlPathGuards:
    """Audit finding H1: predicate logic that keeps control/metrics protected and
    the SPA public, and blocks non-loopback control callers in local mode."""

    def test_public_vs_protected_paths(self):
        from aimos.api import server
        assert server._is_public_path("/") is True
        assert server._is_public_path("/login") is True
        assert server._is_public_path("/assets/app.js") is True
        assert server._is_public_path("/auth/login") is True
        assert server._is_public_path("/api/v2/status") is True
        assert server._is_public_path("/api/decisions") is False
        assert server._is_public_path("/metrics") is False

    def test_control_paths(self):
        from aimos.api import server
        assert server._is_control_path("/api/control/killswitch") is True
        assert server._is_control_path("/api/assistant") is True
        assert server._is_control_path("/api/decisions") is False

    def test_local_client_detection(self):
        from aimos.api import server
        assert server._client_is_local("127.0.0.1") is True
        assert server._client_is_local("::1") is True
        assert server._client_is_local("203.0.113.7") is False
        assert server._client_is_local(None) is False


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


class TestPasswordChange:
    def test_change_password_weak_fails(self, client, admin_tokens):
        resp = client.post("/api/v2/me/password", json={
            "current_password": "AdminPass123!",
            "new_password": "weak",
        }, headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
        assert resp.status_code == 400

    def test_change_password_wrong_current_fails(self, client, admin_tokens):
        resp = client.post("/api/v2/me/password", json={
            "current_password": "WrongPass123!",
            "new_password": "NewStrongPass1!",
        }, headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
        assert resp.status_code == 401

    def test_change_password_updates_and_revokes_refresh(self, client, admin_tokens):
        # Change password.
        resp = client.post("/api/v2/me/password", json={
            "current_password": "AdminPass123!",
            "new_password": "NewStrongPass1!",
        }, headers={"Authorization": f"Bearer {admin_tokens['access_token']}"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Old refresh token is revoked.
        resp = client.post("/auth/refresh")
        assert resp.status_code == 401

        # Login with the new password works; old password fails.
        resp = client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "AdminPass123!",
        })
        assert resp.status_code == 401

        resp = client.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "NewStrongPass1!",
        })
        assert resp.status_code == 200

    def test_ensure_admin_user_does_not_overwrite_password(self, monkeypatch):
        from aimos.saas import auth_service
        from aimos.saas.models import User

        # Seed the admin once.
        SessionLocal = saas_db.get_session_maker()
        with SessionLocal() as session:
            user = auth_service.ensure_admin_user(session)
            old_hash = user.password_hash

        # Change the configured password; existing user must keep the old hash.
        monkeypatch.setenv("AIMOS__SAAS__ADMIN__PASSWORD", "DifferentPass1!")
        with SessionLocal() as session:
            user = session.query(User).filter(User.email == "admin@example.com").first()
            user_after = auth_service.ensure_admin_user(session)
            assert user_after is user
            assert user_after.password_hash == old_hash
            assert auth_service.verify_password("AdminPass123!", user_after.password_hash)
            assert not auth_service.verify_password("DifferentPass1!", user_after.password_hash)


class TestAuthAudit:
    def _audit_rows(self):
        SessionLocal = saas_db.get_session_maker()
        with SessionLocal() as session:
            return [(r.event_type, r.email, r.user_id, r.success) for r in session.query(AuthAuditLog).all()]

    def test_login_audit_recorded(self, client):
        client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
        rows = self._audit_rows()
        assert any(e == "login_attempt" and s is True for e, _, _, s in rows)

        client.post("/auth/login", json={"email": "admin@example.com", "password": "wrong"})
        rows = self._audit_rows()
        assert any(e == "login_attempt" and s is False for e, _, _, s in rows)

    def test_full_auth_lifecycle_audited(self, client, admin_tokens):
        token = admin_tokens["access_token"]
        # Add and remove an exchange key.
        client.post("/api/v2/settings/exchange", json={
            "venue": "binance", "apiKey": "abc", "secret": "def", "testnet": True, "withdraw": False,
        }, headers={"Authorization": f"Bearer {token}"})
        client.delete("/api/v2/settings/exchange/binance", headers={"Authorization": f"Bearer {token}"})

        # Refresh, then logout with the new refresh token (both via httpOnly cookie).
        resp = client.post("/auth/refresh")
        assert resp.status_code == 200
        client.post("/auth/logout")

        # Change password (revokes all refresh tokens; access token is still valid).
        client.post("/api/v2/me/password", json={
            "current_password": "AdminPass123!", "new_password": "NewStrongPass1!",
        }, headers={"Authorization": f"Bearer {token}"})

        rows = self._audit_rows()
        events = [r[0] for r in rows]
        assert "exchange_key_add" in events
        assert "exchange_key_remove" in events
        assert "password_change" in events
        assert "refresh" in events
        assert "logout" in events


class TestFailedLoginAlerts:
    def test_alert_fires_after_threshold(self, client):
        captured = []
        client.app.state.auth_alert_tracker.alert_fn = captured.append
        client.app.state.auth_alert_tracker.threshold = 3

        for _ in range(3):
            resp = client.post("/auth/login", json={
                "email": "admin@example.com",
                "password": "wrong",
            })
            assert resp.status_code == 401

        assert len(captured) >= 1
        assert "admin@example.com" in captured[0]

    def test_successful_login_resets_failure_streak(self, client):
        captured = []
        client.app.state.auth_alert_tracker.alert_fn = captured.append
        client.app.state.auth_alert_tracker.threshold = 3

        # Two failures.
        for _ in range(2):
            client.post("/auth/login", json={"email": "admin@example.com", "password": "wrong"})

        # One success.
        resp = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
        assert resp.status_code == 200

        # One more failure should not trigger an alert (streak was cleared).
        client.post("/auth/login", json={"email": "admin@example.com", "password": "wrong"})
        assert len(captured) == 0


class TestSecurityHeaders:
    def test_csp_and_hardening_headers_present(self, client):
        resp = client.get("/api/v2/status")
        assert resp.status_code == 200
        assert "Content-Security-Policy" in resp.headers
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
        assert resp.headers["X-Frame-Options"] == "DENY"
