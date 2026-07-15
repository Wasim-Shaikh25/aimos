"""Config loader tests (§12, §23.12 — card P0-T4 DoD)."""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from aimos.core import config as cfg
from aimos.core.config import Params, hot_reload, load_params, set_change_journal


def test_loader_validates_full_inventory():
    params = load_params()
    assert isinstance(params, Params)
    # spot-check values threaded from several config files
    assert params.execution.base_risk_pct == 0.5
    assert params.intelligence.fusion_weights.ml == 0.0
    assert params.costs.taker_bps == 7.5
    assert params.tiers.t1_max == 12
    assert "trend_following" in params.plugins
    assert params.mode == "paper"


def test_env_override_applies(monkeypatch):
    monkeypatch.setenv("AIMOS__EXECUTION__BASE_RISK_PCT", "0.25")
    params = load_params(environ={"AIMOS__EXECUTION__BASE_RISK_PCT": "0.25"})
    assert params.execution.base_risk_pct == 0.25


def test_env_override_nested_scalar():
    params = load_params(environ={"AIMOS__INTELLIGENCE__MIN_CONFIDENCE": "0.5"})
    assert params.intelligence.min_confidence == 0.5


def test_bad_range_fails_startup(tmp_path):
    # Copy the config tree, corrupt one value out of range, assert it fails.
    src = cfg.CONFIG_DIR
    dst = tmp_path / "config"
    dst.mkdir()
    for item in src.rglob("*.yaml"):
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.read_text())

    default = yaml.safe_load((dst / "default.yaml").read_text())
    default["execution"]["base_risk_pct"] = 5.0  # > 1.0 → invalid (§23.12)
    (dst / "default.yaml").write_text(yaml.safe_dump(default))

    with pytest.raises(ValidationError):
        load_params(config_dir=dst)


def test_tiers_hysteresis_validation(tmp_path):
    src = cfg.CONFIG_DIR
    dst = tmp_path / "config"
    dst.mkdir()
    for item in src.rglob("*.yaml"):
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.read_text())

    default = yaml.safe_load((dst / "default.yaml").read_text())
    default["tiers"]["promote"] = 40  # promote <= demote → invalid
    default["tiers"]["demote"] = 50
    (dst / "default.yaml").write_text(yaml.safe_dump(default))

    with pytest.raises(ValidationError):
        load_params(config_dir=dst)


def test_hot_reload_only_whitelisted_and_journaled(tmp_path):
    src = cfg.CONFIG_DIR
    dst = tmp_path / "config"
    dst.mkdir()
    for item in src.rglob("*.yaml"):
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.read_text())

    params = load_params(config_dir=dst)

    # Change one whitelisted (base_risk_pct) and one NON-whitelisted (max_positions).
    default = yaml.safe_load((dst / "default.yaml").read_text())
    default["execution"]["base_risk_pct"] = 0.25
    default["execution"]["max_positions"] = 8
    (dst / "default.yaml").write_text(yaml.safe_dump(default))

    changes: list[tuple] = []
    set_change_journal(lambda p, o, n: changes.append((p, o, n)))
    try:
        applied = hot_reload(params, config_dir=dst)
    finally:
        set_change_journal(cfg._default_change_journal)

    assert "execution.base_risk_pct" in applied
    assert params.execution.base_risk_pct == 0.25  # whitelisted change applied
    assert params.execution.max_positions == 4  # structural change NOT applied
    assert ("execution.base_risk_pct", 0.5, 0.25) in changes


# --- completeness test (xfail until later phases consume every key, §23.12) ---


@pytest.mark.xfail(reason="dead-knob completeness enforced once layers consume keys", strict=False)
def test_no_dead_knobs():
    """Every Params leaf key must be referenced in the codebase (§23.12).

    Deferred: the observation/intelligence/execution layers are empty in Phase 0,
    so most keys are not yet consumed. This becomes strict as phases land.
    """
    raise AssertionError("not yet enforced")
