"""FULL golden tick — §25.9 end-to-end incl. NO_TRADE (card P4-T9, permanent CI).

Runs a fully-specified §25.9-style evidence bundle through Layer 2 (intelligence)
and Layer 3 (execution) and asserts the documented outcome: bullish evidence,
honest probabilities, and abstention because the numbers don't clear costs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import (
    Action,
    Behavior,
    Direction,
    Evidence,
    EvidenceBundle,
    Regime,
    Timeframe,
)
from aimos.execution.decide import ExecutionLayer
from aimos.execution.position_sizer import SizingInputs
from aimos.intelligence.understand import IntelligenceLayer
from tests.conftest import make_exec_ctx

TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _ev(name, direction, s, rel, tf=Timeframe.H1, source=None, meta=None):
    return Evidence(source=source or f"eng.{name}", symbol="SOL", timeframe=tf, timestamp=TS,
                    name=name, value=s, direction=direction, strength=s, reliability=rel, meta=meta or {})


def _golden_bundle():
    return EvidenceBundle(symbol="SOL", timestamp=TS, evidences=[
        _ev("structure_trend", Direction.BULLISH, 0.75, 0.65, source="price_action.st",
            meta={"key_levels": {"swing_lows": [146.8], "swing_highs": [153.2], "price": 150.0, "atr": 2.1}}),
        _ev("bos", Direction.BULLISH, 0.60, 0.65, source="price_action.bos"),
        _ev("ema_slope", Direction.BULLISH, 0.50, 0.55, source="momentum.ema"),
        _ev("volume_spike", Direction.BULLISH, 0.55, 0.60, Timeframe.M5, source="volume.vs"),
        _ev("book_imbalance", Direction.BULLISH, 0.30, 0.50, Timeframe.M5, source="orderbook.bi"),
        _ev("rsi_overbought", Direction.BEARISH, 0.50, 0.55, source="momentum.rsi"),
    ])


def test_full_golden_tick_no_trade():
    params = load_params()
    intel = IntelligenceLayer(params)
    execution = ExecutionLayer(params)

    mu = intel.understand(_golden_bundle(), engines_reporting=9)

    # §25.9 steps 2-6: bullish, trending up, continuation
    assert mu.regime is Regime.TRENDING_UP
    assert mu.behavior is Behavior.CONTINUATION
    assert mu.direction_bias is Direction.BULLISH
    assert 0.7 < mu.p_up < 0.9
    assert max(mu.regime_probs.values()) == pytest.approx(0.7)

    # §25.9 steps 7-8: TrendFollowing EV ≤ 0 → chosen NO_TRADE
    ctx = make_exec_ctx(equity=10_000)
    plan = execution.decide(mu, ctx, SizingInputs(volume_24h_usd=1e12, book_depth_1pct_usd=1e12))
    assert plan.action is Action.NO_TRADE  # honest abstention (§25.9)


def test_full_golden_tick_is_deterministic():
    params = load_params()
    intel = IntelligenceLayer(params)
    a = intel.understand(_golden_bundle(), engines_reporting=9)
    b = intel.understand(_golden_bundle(), engines_reporting=9)
    assert a.model_dump() == b.model_dump()  # reproducible (no LLM, no wall clock)
