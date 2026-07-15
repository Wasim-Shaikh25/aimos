"""Risk manager gate tests (§7.4, §23.10B — card P4-T3)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from aimos.core.config import load_params
from aimos.core.schemas import Action, TradePlan
from aimos.execution.risk_manager import RiskManager, RiskState
from tests.conftest import make_exec_ctx, make_mu


def _rm():
    p = load_params()
    return RiskManager(p.execution.model_dump(), p.capacity.model_dump())


def _plan(size=1000.0):
    return TradePlan(plugin="TrendFollowing", symbol="SOL", action=Action.LONG,
                     entry=150.0, stop_loss=145.75, take_profit=160.6, size_quote=size)


def test_kill_switch_vetoes():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(kill_switch=True), 0.5)
    assert d.vetoed and "kill switch" in d.reason


def test_risk_score_veto():
    d = _rm().check(_plan(), make_mu(risk_score=85), make_exec_ctx(), RiskState(), 0.5)
    assert d.vetoed and "risk_score" in d.reason


def test_daily_stop_veto():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(day_pnl_pct=-2.5), 0.5)
    assert d.vetoed and "daily stop" in d.reason


def test_max_positions_veto():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(open_positions=4), 0.5)
    assert d.vetoed and "max positions" in d.reason


def test_portfolio_heat_veto():
    # existing 1.8% + new 0.5% > 2.0% cap
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(open_risk_pct=1.8), 0.5)
    assert d.vetoed and "heat" in d.reason


def test_tier1_gate_veto():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(is_tier1=False), 0.4)
    assert d.vetoed and "Tier 1" in d.reason


def test_intersection_gate_veto():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(),
                    RiskState(is_cross_venue=True, intersection_ok=False), 0.4)
    assert d.vetoed and "intersection" in d.reason


def test_protection_lock_veto():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(protection_locked=True), 0.4)
    assert d.vetoed and "protection" in d.reason


def test_reserve_floor_veto():
    # 20% alloc passes per-asset (25%) and bucket (40%) caps but drops reserve
    # from 45% to 25%, below the 30% floor → reserve gate fires.
    ctx = make_exec_ctx(equity=10_000)
    plan = _plan(size=2000.0)  # 20% alloc
    d = _rm().check(plan, make_mu(), ctx, RiskState(reserve_pct=45.0), 0.4)
    assert d.vetoed and "reserve" in d.reason


def test_clean_plan_passes():
    d = _rm().check(_plan(), make_mu(), make_exec_ctx(), RiskState(), 0.4)
    assert not d.vetoed
    assert d.plan.action is Action.LONG


@settings(max_examples=50)
@given(
    risk_pcts=st.lists(st.floats(min_value=0.1, max_value=1.0), min_size=1, max_size=10),
)
def test_heat_never_breached_by_sequence(risk_pcts):
    # property: the heat gate never lets accumulated risk exceed the cap
    rm = _rm()
    cap = load_params().execution.model_dump()["max_portfolio_heat_pct"]
    accumulated = 0.0
    for rp in risk_pcts:
        d = rm.check(_plan(), make_mu(), make_exec_ctx(), RiskState(open_risk_pct=accumulated), rp)
        if not d.vetoed:
            accumulated += rp
    assert accumulated <= cap + 1e-9
