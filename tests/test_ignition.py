"""Ignition detector + MomentumIgnition tests (§23.11 — card P5-T5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Action, Behavior, Direction
from aimos.observation.ignition import IgnitionDetector, IgnitionInput
from aimos.execution.plugins.momentum_ignition import MomentumIgnition
from tests.conftest import make_exec_ctx, make_mu

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _detector():
    cfg = load_params().ignition.model_dump()
    return IgnitionDetector(cfg, reliability=0.5)


def _organic_input(**over):
    base = dict(ret_5m_z=5.0, rel_vol_1m=6.0, persistence_count=3, move_from_1h_pct=8.0,
                direction=Direction.BULLISH, cross_venue_frac=0.8, book_depth_grew=True,
                spoof_or_divergence=False, corroborated=True, listing_age_days=200, passes_filters=True)
    base.update(over)
    return IgnitionInput(**base)


def test_ignition_triggers_organic():
    r = _detector().detect("PUMP", TS, _organic_input())
    assert r.triggered and not r.blocked
    assert r.evidence.direction is Direction.BULLISH
    assert r.evidence.meta["pnd_suspect"] is False


def test_no_trigger_below_thresholds():
    r = _detector().detect("X", TS, _organic_input(ret_5m_z=2.0))  # z below min
    assert not r.triggered and r.evidence is None


def test_too_late_observe_only():
    r = _detector().detect("X", TS, _organic_input(move_from_1h_pct=20.0))  # > 12% already
    assert not r.triggered


@pytest.mark.parametrize("block", [
    {"cross_venue_frac": 0.2},       # single-venue
    {"book_depth_grew": False},      # hollow book
    {"spoof_or_divergence": True},   # spoof walls
    {"corroborated": False},         # no corroboration
    {"listing_age_days": 30},        # too young (< 90)
    {"passes_filters": False},       # fails filters
])
def test_pnd_block_conditions(block):
    r = _detector().detect("PUMP", TS, _organic_input(**block))
    assert r.triggered and r.blocked
    assert r.evidence.direction is Direction.NEUTRAL  # blocked → NEUTRAL
    assert r.evidence.meta["pnd_suspect"] is True


# ---- MomentumIgnition plugin ----

def _ign_plugin():
    return MomentumIgnition(load_params().ignition.model_dump())


def _ign_mu(organic=True, ts=TS, ema9=150.0, price=150.5):
    # mu.timestamp must be within the entry window of the ignition ts
    return make_mu(timestamp=TS, confidence=0.6, behavior=Behavior.CONTINUATION,
                   key_levels={"price": price, "atr": 2.1,
                               "ignition": {"organic": organic, "ts": ts, "ema9": ema9,
                                            "atr5m": 2.0, "price": price}})


def test_momentum_ignition_proposes_on_organic_pullback():
    plan = _ign_plugin().propose(_ign_mu(), make_exec_ctx())
    assert plan is not None and plan.action is Action.LONG
    assert plan.meta["mode_tag"] == "ignition"
    assert plan.meta["sub_book"]["max_equity_pct"] == 5  # caged sub-book


def test_momentum_ignition_skips_blocked():
    assert _ign_plugin().propose(_ign_mu(organic=False), make_exec_ctx()) is None


def test_momentum_ignition_entry_window_expired():
    stale = TS - timedelta(minutes=30)  # ignition 30 min ago > 15 min window
    mu = _ign_mu(ts=stale)
    assert _ign_plugin().propose(mu, make_exec_ctx()) is None


def test_momentum_ignition_blocks_euphoria():
    mu = _ign_mu()
    mu.behavior = Behavior.EUPHORIA
    assert not _ign_plugin().can_trade(mu)
