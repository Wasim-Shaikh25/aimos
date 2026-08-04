"""Tests for /healthz and /readyz (REQ-6)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from aimos.api.server import AppState, create_app
from aimos.journal.journal import Journal
from aimos.runtime.serve import build_app


def test_healthz_is_public_and_live():
    state = AppState(journal=Journal(":memory:"))
    app = create_app(state)
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_readyz_reports_not_ready():
    """When the health provider reports not ready, /readyz returns 503."""
    state = AppState(
        journal=Journal(":memory:"),
        health_provider=lambda: {"ready": False, "journal_writable": False},
    )
    app = create_app(state)
    with TestClient(app) as client:
        r = client.get("/readyz")
        assert r.status_code == 503


def test_readyz_reports_ready():
    state = AppState(
        journal=Journal(":memory:"),
        health_provider=lambda: {"ready": True, "journal_writable": True},
    )
    app = create_app(state)
    with TestClient(app) as client:
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["ready"] is True


def test_readyz_after_loop_tick(monkeypatch):
    """Integration: running the serve stack eventually makes /readyz 200."""
    monkeypatch.setenv("AIMOS__PAPER__LOOP_SECONDS", "0.1")
    monkeypatch.setenv("AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS", "60")
    app = build_app(offline=True)
    with TestClient(app) as client:
        time.sleep(0.4)
        r = client.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body.get("ready") is True
        assert body.get("journal_writable") is True
        assert body.get("heartbeat_age_seconds") is not None
