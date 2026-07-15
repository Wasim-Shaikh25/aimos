"""Risk analytics tests (§24.1-24.4 + factor engine — cards P5-T7, P5-T6, P5-T9)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Action, Direction
from aimos.observation.factor_engine import FactorEngine
from aimos.risk.analytics import alpha_beta, historical_var_es
from aimos.risk.counterparty import CounterpartyRisk, DegradeLevel
from aimos.risk.scenario import PositionRisk, ScenarioEngine, scenario_pnl
from aimos.backtest.second_opinion import cross_check
from aimos.execution.plugins.smart_dca import build_ladder

TS = datetime(2026, 7, 9, tzinfo=timezone.utc)


# ---- scenario / stress (§24.1) ----

def test_scenario_beta_propagation_hand_computed():
    # long $10k alt with beta 1.5, BTC -30% → move -45% → -$4500 → -45% of $10k equity
    positions = [PositionRisk("SOL", 10_000, Action.LONG, beta=1.5)]
    pnl = scenario_pnl(positions, equity=10_000, btc_shock=-0.30)
    assert pnl == pytest.approx(-45.0)


def test_scenario_binding_gate_blocks():
    eng = ScenarioEngine(load_params().scenarios.model_dump())
    # a big long book → btc_crash_30 loss > 8% cap → blocks new risk
    positions = [PositionRisk("ETH", 20_000, Action.LONG, beta=1.2)]
    assert eng.blocks_new_risk(positions, equity=10_000)


def test_scenario_short_profits_on_crash():
    positions = [PositionRisk("BTC", 10_000, Action.SHORT, beta=1.0)]
    assert scenario_pnl(positions, 10_000, btc_shock=-0.30) > 0


# ---- counterparty (§24.2) ----

def test_venue_cap_veto():
    cp = CounterpartyRisk(load_params().counterparty.model_dump())
    # 40% cap; existing 35% + new 10% = 45% → veto
    assert cp.vetoes_new_position("binance", exposure_pct=35.0, new_alloc_pct=10.0)
    assert not cp.vetoes_new_position("binance", exposure_pct=20.0, new_alloc_pct=10.0)


def test_degrade_ladder():
    assert CounterpartyRisk.degrade_level(0, False) is DegradeLevel.OK
    assert CounterpartyRisk.degrade_level(1, False) is DegradeLevel.WATCH
    assert CounterpartyRisk.degrade_level(2, False) is DegradeLevel.ALERT
    assert CounterpartyRisk.degrade_level(0, True) is DegradeLevel.CRITICAL


# ---- VaR/ES + attribution (§24.3-24.4) ----

def test_var_es_historical_hand_computed():
    # 20 returns; 95% VaR = 5th percentile loss
    returns = [-0.10, -0.08, -0.05, -0.03, -0.02] + [0.01] * 15
    v = historical_var_es(returns, confidence=0.95)
    assert v.var_pct > 0  # a loss magnitude
    assert v.es_pct >= v.var_pct  # ES at least as severe as VaR


def test_alpha_beta_regression():
    rng = np.random.default_rng(0)
    bench = rng.normal(0, 0.02, 200)
    strat = 0.5 * bench + 0.001 + rng.normal(0, 0.001, 200)  # beta 0.5, positive alpha
    a = alpha_beta(strat, bench)
    assert a.beta == pytest.approx(0.5, abs=0.1)
    assert a.alpha_annualized > 0


# ---- factor engine (§20.1, P5-T6) ----

def test_factor_engine_cross_sectional_evidence():
    obs = load_params().observation.model_dump()
    factors = {"alphas": [{"id": "mom1", "ic_sign": 1, "lookback": 1}]}
    fe = FactorEngine(obs, factors, reliability=0.55)
    # 3-asset panel; one asset rising fastest → highest z → strong bullish factor
    panel = {"A": [100, 101, 102, 110], "B": [100, 100, 100, 100], "C": [100, 99, 98, 95]}
    out = fe.emit(panel, TS)
    assert out["A"][0].name == "factor_mom1"
    assert out["A"][0].direction is Direction.BULLISH  # top performer
    assert out["C"][0].direction is Direction.BEARISH  # worst performer


# ---- Jesse cross-check (§21.5, P5-T9) ----

def test_jesse_divergence_flagged():
    ours = [100.0, 130.0]      # +30%
    jesse = [100.0, 110.0]     # +10% → 66% divergence > 15%
    report = cross_check(ours, jesse)
    assert report.diverged and report.proposal is not None


def test_jesse_agreement_no_proposal():
    report = cross_check([100.0, 130.0], [100.0, 129.0])  # ~3% divergence
    assert not report.diverged and report.proposal is None


# ---- SmartDCA ladder math (§7.2 P6, P5-T9) ----

def test_smartdca_ladder_math():
    ladder = build_ladder(mid=100.0, atr=2.0, offsets=[0, -1, -2, -3], size_pcts=[15, 20, 30, 35])
    assert [t["price"] for t in ladder] == [100.0, 98.0, 96.0, 94.0]
    assert sum(t["size_pct"] for t in ladder) == 100
