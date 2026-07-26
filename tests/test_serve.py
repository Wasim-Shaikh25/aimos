"""Full-stack serve entrypoint test (API + dashboard + background paper loop)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from aimos.runtime.serve import build_app


def test_serve_app_full_stack_offline():
    app = build_app(offline=True)  # synthetic data, no network/keys
    with TestClient(app) as client:  # lifespan runs the background loop
        time.sleep(1.5)  # let a couple of ticks journal
        stats = client.get("/api/journal/stats").json()
        assert stats["n_decisions"] >= 1  # background loop is producing decisions
        eq = client.get("/api/equity").json()
        assert isinstance(eq["equity"], list) and eq["equity"][0] == 10000.0
        markets = client.get("/api/markets").json()["markets"]
        assert markets and "regime" in markets[0]
        base = markets[0]["symbol"]
        candles = client.get(f"/api/candles/{base}").json()
        assert "candles" in candles and "venues" in candles
        if candles["candles"]:
            venue = candles["venues"][0]
            assert venue in candles["candles"]
            assert candles["candles"][venue][0]["open"] > 0
        # controls still CONFIRM-gated through the same app
        assert client.post("/api/control/pause", json={}).status_code == 403


def test_serve_wires_telegram_and_persists_journal(tmp_path, monkeypatch):
    # telegram_enabled + status ticks + a file journal → all wired in one process.
    monkeypatch.setenv("AIMOS__FEATURES__TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("AIMOS__PAPER__TELEGRAM_STATUS_TICKS", "1")
    monkeypatch.setenv("AIMOS__PAPER__JOURNAL_PATH", str(tmp_path / "aimos.sqlite"))
    app = build_app(offline=True)  # no token → Telegram dry-run (never networks)
    with TestClient(app) as client:
        time.sleep(1.5)
        assert client.get("/api/journal/stats").json()["n_decisions"] >= 1
    assert (tmp_path / "aimos.sqlite").exists()  # decisions persisted to disk


def test_serve_serves_built_dashboard_if_present():
    app = build_app(offline=True)
    with TestClient(app) as client:
        root = client.get("/")
        # if the dashboard was built, "/" serves the SPA; else the API root 404s
        if root.status_code == 200 and "text/html" in root.headers.get("content-type", ""):
            assert 'id="root"' in root.text
            # SPA deep-link fallback returns the app shell, not 404
            assert 'id="root"' in client.get("/positions").text
