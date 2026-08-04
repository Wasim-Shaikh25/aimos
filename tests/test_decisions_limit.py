"""Tests for the `/api/decisions` limit bound (REQ-3)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from aimos.runtime.serve import build_app


@pytest.mark.parametrize("limit,expected_status", [
    (1, 200),
    (50, 200),
    (500, 200),
    (0, 422),
    (501, 422),
    (-1, 422),
])
def test_decisions_limit_bound(monkeypatch, limit, expected_status):
    """`limit` is clamped to [1, 500] at the API level."""
    monkeypatch.setenv("AIMOS__PAPER__LOOP_SECONDS", "0.1")
    app = build_app(offline=True)
    with TestClient(app) as client:
        time.sleep(0.3)  # give the paper loop a tick
        r = client.get(f"/api/decisions?limit={limit}")
        assert r.status_code == expected_status, r.text
        if expected_status == 200:
            assert "decisions" in r.json()
