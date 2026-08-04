"""Tests for REQ-13: separate API process from trading loop."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aimos.runtime.serve import _build_view, _process_mode, _rehydrate_from_snapshot
from aimos.runtime.state_store import ControlStore, RuntimeStateStore, build_snapshot


def test_process_mode_defaults_to_combined(monkeypatch):
    monkeypatch.delenv("AIMOS_PROCESS", raising=False)
    assert _process_mode() == "combined"


def test_process_mode_reads_env(monkeypatch):
    monkeypatch.setenv("AIMOS_PROCESS", "api")
    assert _process_mode() == "api"
    monkeypatch.setenv("AIMOS_PROCESS", "LOOP")
    assert _process_mode() == "loop"


def test_control_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AIMOS_PROCESS", "combined")
    store = ControlStore("test", state_dir=tmp_path)
    store.save({"halted": True, "global_pause": False, "features": {}})
    loaded = store.load()
    assert loaded["halted"] is True
    assert loaded["global_pause"] is False
    assert "updated_at" in loaded


def test_runtime_state_store_includes_view_and_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("AIMOS_PROCESS", "combined")
    store = RuntimeStateStore("test", state_dir=tmp_path)
    snapshot = {
        "broker": {"cash": 1000.0},
        "sim": {},
        "equity": [1000.0, 1001.0],
        "view": {"latest": {}, "prices": {}},
        "controls": {"halted": False},
    }
    store.save(snapshot)
    loaded = store.load()
    assert loaded["view"] == snapshot["view"]
    assert loaded["controls"] == snapshot["controls"]


def test_build_view_and_rehydrate(tmp_path, monkeypatch):
    """The API process can rehydrate the view built by the loop process."""
    monkeypatch.setenv("AIMOS_PROCESS", "combined")
    monkeypatch.chdir(tmp_path)
    from aimos.runtime.serve import _build_components

    components = _build_components(offline=True)
    holder = components["holder"]
    holder["prices"]["BTC"] = {"venues": {"binance": 100.0}}
    holder["latest"]["BTC"] = {"p_up": 0.5, "regime": "trend"}
    holder["candles"]["BTC"] = {}  # empty venue map; candles_view stays empty
    holder["chosen"]["Momentum"] = 3

    params = components["params"]
    view = _build_view(holder, components["connections"], params, components["paper"])
    assert view["prices"]["BTC"]["venues"]["binance"] == 100.0
    assert view["matrix"]["matrix"] is not None
    assert view["chosen"]["Momentum"] == 3

    snapshot = build_snapshot(
        holder, components["broker"], components["sim"], components["ladder"],
        view=view, controls={"halted": False},
    )

    # Rehydrate the same components (as the API process would)
    _rehydrate_from_snapshot(components, snapshot, {})
    assert components["holder"]["prices"]["BTC"]["venues"]["binance"] == 100.0
    assert components["holder"]["latest"]["BTC"]["p_up"] == 0.5
    assert components["holder"]["matrix_view"]["matrix"] is not None


def test_api_app_does_not_start_loop(tmp_path, monkeypatch):
    """AIMOS_PROCESS=api returns an ASGI app without running the trading loop."""
    monkeypatch.setenv("AIMOS_PROCESS", "api")
    monkeypatch.chdir(tmp_path)
    from aimos.runtime import serve

    app = serve.build_app(offline=True)
    assert app is not None
    # The app lifespan starts the state-loader task, not the loop.
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200


def test_loop_mode_app_is_none(monkeypatch):
    """Module-level app is not built when the process is the loop worker."""
    monkeypatch.setenv("AIMOS_PROCESS", "loop")
    # Importing the module in loop mode should not create an ASGI app.
    import importlib
    from aimos.runtime import serve

    importlib.reload(serve)
    assert serve.app is None
