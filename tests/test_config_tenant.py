"""Per-tenant config overlay."""

from __future__ import annotations

from aimos.saas import db as saas_db
from aimos.saas.config_tenant import _deep_merge, load_params_for_org
from aimos.saas.settings_store import SettingsStore


def test_deep_merge_overrides_nested_and_scalar():
    base = {"features": {"live_data": True, "scalp_enabled": True}, "paper": {"max_symbols": 10}}
    overlay = {"features": {"scalp_enabled": False}, "paper": {"max_symbols": 5}}
    merged = _deep_merge(base, overlay)
    assert merged["features"]["live_data"] is True
    assert merged["features"]["scalp_enabled"] is False
    assert merged["paper"]["max_symbols"] == 5


def test_load_params_for_org_returns_base_when_saas_disabled(monkeypatch):
    monkeypatch.setenv("AIMOS__SAAS__ENABLED", "false")
    params = load_params_for_org("local")
    assert params.features.model_dump().get("saas_enabled") is False


def test_load_params_for_org_applies_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMOS__SAAS__ENABLED", "true")
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AIMOS_SECRETS_DIR", str(tmp_path / "secrets"))
    saas_db._engine = None
    saas_db._SessionLocal = None
    SettingsStore._key = None

    SettingsStore("default").update_config({
        "features": {"scalp_enabled": False},
        "paper": {"max_symbols": 3},
    })

    params = load_params_for_org("org1")
    assert params.features.model_dump().get("scalp_enabled") is False
    assert params.paper.model_dump().get("max_symbols") == 3
    # values not overridden remain from base
    assert params.features.model_dump().get("live_data") is True
