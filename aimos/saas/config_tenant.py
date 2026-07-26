"""Per-tenant configuration overlay.

Loads the base ``Params`` tree and deep-merges any overrides stored in the
organization's ``OrganizationConfig`` row. Used by the runtime when it boots for a
specific ``AIMOS_RUNTIME_ORG_ID``.
"""

from __future__ import annotations

from aimos.core.config import Params, load_params
from aimos.saas.settings import get_saas_config
from aimos.saas.settings_store import SettingsStore


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = base.copy()
    for key, value in overlay.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_params_for_org(org_id: str) -> Params:
    """Return the base config with the single-user settings overrides applied."""
    params = load_params()
    if not get_saas_config().enabled:
        return params
    # Single-user deployments use one settings row; org_id is kept for
    # backward compatibility with per-tenant paths and the runtime org flag.
    settings_id = "default"
    overrides = SettingsStore(settings_id).get_config()
    if overrides:
        raw = params.model_dump()
        merged = _deep_merge(raw, overrides)
        return Params.model_validate(merged)
    return params
