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
        # controls still CONFIRM-gated through the same app
        assert client.post("/api/control/pause", json={}).status_code == 403


def test_serve_serves_built_dashboard_if_present():
    app = build_app(offline=True)
    with TestClient(app) as client:
        root = client.get("/")
        # if the dashboard was built, "/" serves the SPA; else the API root 404s
        if root.status_code == 200 and "text/html" in root.headers.get("content-type", ""):
            assert 'id="root"' in root.text
            # SPA deep-link fallback returns the app shell, not 404
            assert 'id="root"' in client.get("/positions").text
