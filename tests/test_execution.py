"""Evaluator + sizer + plugin geometry tests (§7.1-7.5, §23.10, §25.4-25.9 —
cards P4-T1, P4-T2)."""

from __future__ import annotations

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Action, Direction, Regime
from aimos.execution.evaluator import Evaluator, expected_value, risk_bps
from aimos.execution.plugins.risk_off import RiskOff
from aimos.execution.plugins.trend_following import TrendFollowing
from aimos.execution.position_sizer import PositionSizer, SizingInputs
from tests.conftest import make_exec_ctx, make_mu


def _params():
    return load_params()


def _execc():
    return _params().execution.model_dump()


def _tf_plugin():
    return TrendFollowing(_params().plugins["trend_following"].model_dump())


# ---- §25.9 step 7-8 golden (P4-T1) ----

def test_golden_trend_following_geometry_and_ev():
    mu = make_mu()
    ctx = make_exec_ctx()
    plan = _tf_plugin().propose(mu, ctx)
    assert plan.entry == pytest.approx(150.0)
    assert plan.stop_loss == pytest.approx(145.75)  # 146.8 - 0.5*2.1
    assert plan.take_profit == pytest.approx(160.625)  # 2.5R
    assert risk_bps(plan) == pytest.approx(283.33, abs=0.5)
    assert plan.expected_costs_bps == pytest.approx(19.0)  # 7.5*2 + 2 + 2
    assert plan.confidence == pytest.approx(0.2996, abs=0.001)
    ev = expected_value(plan, float(_execc()["losing_trade_r"]))
    assert ev == pytest.approx(-0.017, abs=0.01)  # §25.9


def test_golden_chosen_no_trade():
    mu = make_mu()
    ctx = make_exec_ctx()
    plan = _tf_plugin().propose(mu, ctx)
    ro = RiskOff({}).propose(mu, ctx)
    chosen = Evaluator(_execc()).evaluate([plan, ro], mu)
    assert chosen.action is Action.NO_TRADE  # §25.9 step 8


def test_evaluator_takes_positive_ev_winner():
    # a plan with high confidence + good rr → positive EV → beats NO_TRADE
    mu = make_mu(confidence=0.9, opportunity_score=90, risk_score=20,
                 regime_probs={"trending_up": 0.9, "ranging": 0.1})
    ctx = make_exec_ctx()
    plan = _tf_plugin().propose(mu, ctx)
    ro = RiskOff({}).propose(mu, ctx)
    chosen = Evaluator(_execc()).evaluate([plan, ro], mu)
    assert chosen.action is Action.LONG
    assert chosen.plugin == "TrendFollowing"


def test_cost_fraction_gate_rejects():
    # costs > 25% of expected gross move → rejected before scoring
    mu = make_mu(confidence=0.9)
    ctx = make_exec_ctx(slippage_entry_bps=200, slippage_exit_bps=200)  # huge costs
    plan = _tf_plugin().propose(mu, ctx)
    ro = RiskOff({}).propose(mu, ctx)
    chosen = Evaluator(_execc()).evaluate([plan, ro], mu)
    assert chosen.action is Action.NO_TRADE


# ---- sizer + capacity MIN chain (P4-T1, §23.10A) ----

def test_sizer_risk_based_size():
    mu = make_mu()
    ctx = make_exec_ctx(equity=10_000)
    plan = _tf_plugin().propose(mu, ctx)
    plan.confidence = 0.6  # → conf_scale = 1.0
    sizer = PositionSizer(_execc())
    # no capacity limits → risk-based size governs
    res = sizer.size(plan, ctx, SizingInputs(volume_24h_usd=1e12, book_depth_1pct_usd=1e12))
    frac_risk = abs(plan.entry - plan.stop_loss) / plan.entry
    expected = 10_000 * 0.005 * 1.0 / frac_risk  # base_risk 0.5%
    assert res.size_quote == pytest.approx(expected, rel=0.01)


def test_capacity_depth_cap_binds_50k_to_8k():
    # risk math allows ~$50k but book depth allows only ~$8k → depth cap binds
    mu = make_mu(confidence=0.6)
    ctx = make_exec_ctx(equity=1_000_000)  # large equity → big risk-based size
    plan = _tf_plugin().propose(mu, ctx)
    plan.confidence = 0.6
    sizer = PositionSizer(_execc())
    # depth 1% = ~$53.3k → 15% cap = $8k
    res = sizer.size(plan, ctx, SizingInputs(volume_24h_usd=1e15, book_depth_1pct_usd=53_333.0))
    assert res.size_quote == pytest.approx(8_000.0, rel=0.01)
    assert any("depth cap" in r for r in res.reasons)


def test_sizer_below_minimum_rejected():
    mu = make_mu(confidence=0.6)
    ctx = make_exec_ctx(equity=100)  # tiny equity
    plan = _tf_plugin().propose(mu, ctx)
    plan.confidence = 0.6
    sizer = PositionSizer(_execc())
    res = sizer.size(plan, ctx, SizingInputs(min_notional_usd=10_000))
    assert res.rejected
    assert any("below minimum" in r for r in res.reasons)


# ---- plugin geometry (P4-T2) ----

def test_trend_following_requires_bias_agreement():
    mu = make_mu(direction_bias=Direction.BEARISH)  # regime up but bias down
    assert _tf_plugin().propose(mu, make_exec_ctx()) is None


def test_pullback_requires_continuation_and_ema_proximity():
    from aimos.execution.plugins.pullback import Pullback
    p = Pullback(_params().plugins["pullback"].model_dump())
    # price far from EMA → None
    mu = make_mu(key_levels={"price": 150.0, "atr": 2.1, "ema50": 130.0,
                             "swing_highs": [160.0], "swing_lows": [146.8]})
    assert p.propose(mu, make_exec_ctx()) is None
    # price within 0.75*ATR of EMA + continuation → proposes
    mu2 = make_mu(key_levels={"price": 149.5, "atr": 2.1, "ema50": 149.0,
                              "swing_highs": [160.0], "swing_lows": [146.8]})
    plan = p.propose(mu2, make_exec_ctx())
    assert plan is not None and plan.action is Action.LONG
    assert plan.entry == pytest.approx(149.0)  # limit at EMA


def test_mean_reversion_ranging_geometry():
    from aimos.execution.plugins.mean_reversion import MeanReversion
    mr = MeanReversion(_params().plugins["mean_reversion"].model_dump())
    mu = make_mu(regime=Regime.RANGING, regime_probs={"ranging": 0.7},
                 direction_bias=Direction.BULLISH, coin_health=70,
                 key_levels={"price": 150.0, "atr": 2.1, "swing_highs": [153.2], "swing_lows": [146.8]})
    plan = mr.propose(mu, make_exec_ctx())
    assert plan is not None and plan.action is Action.LONG
    assert plan.entry == pytest.approx(146.8)  # support boundary
    assert plan.take_profit == pytest.approx((153.2 + 146.8) / 2)  # mid-range
