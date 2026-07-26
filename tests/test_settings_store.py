"""Single-user settings store and endpoints."""

from __future__ import annotations

from aimos.saas import db as saas_db
from aimos.saas.settings_store import SettingsStore, UserSettings


def test_settings_store_encrypts_and_redacts_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    saas_db._engine = None
    saas_db._SessionLocal = None

    store = SettingsStore("default")
    store.set_exchange("binance", {
        "exchange_id": "binance",
        "apiKey": "super-secret-key",
        "secret": "super-secret-secret",
        "testnet": True,
        "withdraw": False,
    })

    public = store.get_exchanges()
    assert public["binance"]["has_key"] is True
    assert "apiKey" not in public["binance"]
    assert "secret" not in public["binance"]

    creds = store.get_exchange_credentials("binance")
    assert creds["apiKey"] == "super-secret-key"
    assert creds["secret"] == "super-secret-secret"


def test_settings_store_update_config_deep_merges(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    saas_db._engine = None
    saas_db._SessionLocal = None

    store = SettingsStore("default")
    store.update_config({"features": {"scalp_enabled": True}, "paper": {"max_symbols": 3}})
    store.update_config({"features": {"cross_exchange_enabled": False}})

    cfg = store.get_config()
    assert cfg["features"]["scalp_enabled"] is True
    assert cfg["features"]["cross_exchange_enabled"] is False
    assert cfg["paper"]["max_symbols"] == 3


def test_settings_store_delete_exchange(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMOS__SAAS__DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    saas_db._engine = None
    saas_db._SessionLocal = None

    store = SettingsStore("default")
    store.set_exchange("binance", {"apiKey": "x", "secret": "y"})
    assert store.delete_exchange("binance") is True
    assert store.get_exchange_credentials("binance") is None
