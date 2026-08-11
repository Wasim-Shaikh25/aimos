"""Single-user configuration overlay from the settings store."""

from __future__ import annotations

from typing import Any

from aimos.core.config import Params, load_params
from aimos.settings.settings_store import SettingsStore


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in overlay.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_params_for_user(database_url: str = "") -> Params:
    """Return the base config with the single-user settings overrides applied."""
    params = load_params()
    url = database_url or params.model_dump().get("storage", {}).get("database_url", "")
    store = SettingsStore("default", database_url=url)
    overrides = store.get_config()
    if overrides:
        raw = params.model_dump()
        merged = _deep_merge(raw, overrides)
        return Params.model_validate(merged)
    return params
