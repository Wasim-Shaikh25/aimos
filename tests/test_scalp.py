"""Scalp (§17): MomentumScalp firing + the proxy micro-engine + flag-gated wiring."""

from __future__ import annotations

from aimos.core.clock import LiveClock
from aimos.core.config import load_params
from aimos.execution.plugins import build_plugins
from aimos.execution.plugins.momentum_scalp import MomentumScalp
from aimos.observation.runner import build_engines
from tests.conftest import make_exec_ctx, make_mu


def _scalp_cfg():
    return load_params().scalp.model_dump()


def _scalp_kl(**over):
    kl = {"price": 150.0, "scalp": {"spread_bps": 3.0, "atr1m": 1.0, "book_imbalance": 0.5,
          "volume_spike": True, "best_bid": 149.9, "best_ask": 150.1}}
    kl["scalp"].update(over)
    return kl


def test_momentum_scalp_fires_on_spike_and_imbalance():
    plug = MomentumScalp(_scalp_cfg())
    mu = make_mu(confidence=0.6, key_levels=_scalp_kl())  # BULLISH bias by default
    plan = plug.propose(mu, make_exec_ctx())
    assert plan is not None and plan.plugin == "MomentumScalp"
    assert plan.meta["mode_tag"] == "scalp" and plan.meta["order_type"] == "post_only"
    assert plan.expected_rr >= _scalp_cfg()["micro"]["s1_min_rr"]


def test_scalp_skips_when_spread_too_wide():
    plug = MomentumScalp(_scalp_cfg())
    mu = make_mu(confidence=0.6, key_levels=_scalp_kl(spread_bps=99.0))
    assert plug.propose(mu, make_exec_ctx()) is None


def test_scalp_skips_without_volume_spike():
    plug = MomentumScalp(_scalp_cfg())
    mu = make_mu(confidence=0.6, key_levels=_scalp_kl(volume_spike=False))
    assert plug.propose(mu, make_exec_ctx()) is None


def test_scalp_registered_only_when_flagged(monkeypatch):
    # flag OFF → neither the plugin nor the micro-engine is built
    monkeypatch.setenv("AIMOS__FEATURES__SCALP_ENABLED", "false")
    p_off = load_params()
    assert "MomentumScalp" not in [x.name for x in build_plugins(p_off)]
    assert "scalp_micro_engine" not in [e.name for e in build_engines(p_off, LiveClock())]
    # flag ON → both are registered
    monkeypatch.setenv("AIMOS__FEATURES__SCALP_ENABLED", "true")
    p_on = load_params()
    assert "MomentumScalp" in [x.name for x in build_plugins(p_on)]
    assert "scalp_micro_engine" in [e.name for e in build_engines(p_on, LiveClock())]
