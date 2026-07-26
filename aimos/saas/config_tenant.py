"""Per-tenant configuration overlay.

Loads the base ``Params`` tree and deep-merges any overrides stored in the
organization's ``OrganizationConfig`` row. Used by the runtime when it boots for a
specific ``AIMOS_RUNTIME_ORG_ID``.
"""

from __future__ import annotations

from aimos.core.config import Params, load_params
from aimos.saas.db import get_session_maker
from aimos.saas.models import OrganizationConfig
from aimos.saas.settings import get_saas_config


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = base.copy()
    for key, value in overlay.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_params_for_org(org_id: str) -> Params:
    """Return the base config with the organization's overrides applied."""
    params = load_params()
    if not get_saas_config().enabled:
        return params
    session = get_session_maker()()
    try:
        cfg = session.get(OrganizationConfig, org_id)
        if cfg and cfg.overrides:
            raw = params.model_dump()
            merged = _deep_merge(raw, cfg.overrides)
            return Params.model_validate(merged)
    finally:
        session.close()
    return params
