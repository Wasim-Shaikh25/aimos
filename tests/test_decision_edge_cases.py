"""Adversarial edge cases for the decision path (evaluator / sizer / decide).

Regression coverage for defects found in end-to-end probing: a concentration-
capped asset must not yield a zero-notional "trade"; non-finite geometry must
never reach a sized order; and a stop-less candidate must not win evaluation and
suppress a valid one. Positive controls confirm the normal path still trades.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import (
    Action, Behavior, CapacityCaps, Direction, ExecContext,
    MarketUnderstanding, Position, Regime, TradePlan,
)
from aimos.execution.decide import ExecutionLayer
from aimos.execution.evaluator import Evaluator
from aimos.execution.position_sizer import PositionSizer, SizingInputs
from aimos.execution.risk_manager import RiskState

CAPS = CapacityCaps(max_equity_pct_per_asset=10.0, max_pct_of_24h_volume=1.0,
                    max_pct_of_book_depth=10.0, max_exit_slippage_bps=50.0, stress_exit_bps=200.0)


@pytest.fixture(scope="module")
def params():
    return load_params()


def _mu(**kw):
    d = dict(symbol="BTC", timestamp=datetime.now(timezone.utc), regime=Regime.TRENDING_UP,
             regime_probs={"trending_up": 0.7}, behavior=Behavior.CONTINUATION, behavior_probs={},
             direction_bias=Direction.BULLISH, p_up=0.6, horizon_minutes=240, confidence=0.7,
             coin_health=80.0, opportunity_score=60.0, risk_score=20.0,
             key_levels={"price": 100.0, "atr": 2.0, "swing_lows": [96.0], "swing_highs": [104.0]},
             engine_votes={}, reasons=[])
    d.update(kw)
    return MarketUnderstanding(**d)


def _ctx(equity=10000.0, positions=None):
    return ExecContext(equity_usdt=equity, open_positions=positions or [], portfolio_heat_pct=0.0,
                       fee_taker_bps=5.0, fee_maker_bps=1.0, slippage_entry_bps=3.0,
                       slippage_exit_bps=3.0, venue="binance", caps=CAPS)


def _plan(**kw):
    d = dict(plugin="TrendFollowing", symbol="BTC", action=Action.LONG, entry=100.0,
             stop_loss=98.0, take_profit=106.0, expected_rr=3.0, expected_costs_bps=16.0, confidence=0.7)
    d.update(kw)
    return TradePlan(**d)


def _si():
    return SizingInputs(volume_24h_usd=1e7, book_depth_1pct_usd=1e6)


# -- sizer -------------------------------------------------------------------

def test_concentration_capped_asset_is_rejected_not_zero_size(params):
    """Asset already at its concentration cap must NOT yield a size-0 'trade'."""
    sz = PositionSizer(params.execution.model_dump())
    held = Position(symbol="BTC", venue="binance", side=Action.LONG, qty=1000.0, entry=100.0,
                    stop=98.0, opened_at=datetime.now(timezone.utc), plugin="X",
                    decision_id="d", mode_tag="swing")
    res = sz.size(_plan(), _ctx(positions=[held]), SizingInputs())
    assert res.rejected is True
    assert res.size_quote is None


def test_nonfinite_geometry_rejected_by_sizer(params):
    sz = PositionSizer(params.execution.model_dump())
    for bad in (float("nan"), float("inf")):
        assert sz.size(_plan(entry=bad), _ctx(), _si()).rejected is True
        assert sz.size(_plan(stop_loss=bad), _ctx(), _si()).rejected is True


def test_entry_equals_stop_rejected(params):
    sz = PositionSizer(params.execution.model_dump())
    assert sz.size(_plan(entry=100.0, stop_loss=100.0), _ctx(), _si()).rejected is True


def test_normal_plan_still_sizes(params):
    """Positive control — a healthy plan sizes to a real positive notional."""
    sz = PositionSizer(params.execution.model_dump())
    res = sz.size(_plan(), _ctx(), _si())
    assert res.rejected is False
    assert res.size_quote is not None and res.size_quote > 0


# -- evaluator ---------------------------------------------------------------

def test_stopless_candidate_never_wins(params):
    """A candidate with no stop distance must not out-score a NO_TRADE baseline."""
    ev = Evaluator(params.execution.model_dump())
    stopless = _plan(stop_loss=None, entry=100.0, expected_rr=9.0, expected_costs_bps=9999.0)
    nt = TradePlan(plugin="RiskOff", symbol="BTC", action=Action.NO_TRADE)
    winner = ev.evaluate([stopless, nt], _mu())
    assert winner.action is Action.NO_TRADE


def test_nonfinite_ev_candidate_dropped(params):
    ev = Evaluator(params.execution.model_dump())
    nt = TradePlan(plugin="RiskOff", symbol="BTC", action=Action.NO_TRADE)
    for bad in (float("nan"), float("inf")):
        winner = ev.evaluate([_plan(expected_rr=bad), nt], _mu())
        assert math.isfinite(winner.score)


def test_negative_rr_candidate_dropped(params):
    ev = Evaluator(params.execution.model_dump())
    nt = TradePlan(plugin="RiskOff", symbol="BTC", action=Action.NO_TRADE)
    assert ev.evaluate([_plan(expected_rr=-2.0), nt], _mu()).action is Action.NO_TRADE


# -- end-to-end decide() -----------------------------------------------------

def test_decide_never_returns_nonpositive_or_nonfinite_size(params):
    """No hostile MU may produce a tradeable plan with size ≤ 0 or non-finite."""
    el = ExecutionLayer(params)
    held = Position(symbol="BTC", venue="binance", side=Action.LONG, qty=1000.0, entry=100.0,
                    stop=98.0, opened_at=datetime.now(timezone.utc), plugin="X",
                    decision_id="d", mode_tag="swing")
    hostile = [
        _mu(),  # normal (control — may or may not trade, but if it does, size>0)
        _mu(key_levels={"price": float("nan"), "atr": 2.0, "swing_lows": [96.0], "swing_highs": [104.0]}),
        _mu(key_levels={"price": 0.0, "atr": 2.0}),
        _mu(key_levels={}),
    ]
    contexts = [_ctx(), _ctx(positions=[held]), _ctx(equity=-5000.0)]
    for m in hostile:
        for c in contexts:
            dec = el.decide(m, c, _si(), RiskState())
            if dec.action in (Action.LONG, Action.SHORT):
                assert dec.size_quote is not None
                assert math.isfinite(dec.size_quote) and dec.size_quote > 0
