"""PaperBroker + cost model tests (§7.6, §9.2, §23.9 — card P4-T6)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.backtest.costs import CostModel, funding_cost_bps, total_forward_costs_bps
from aimos.core.schemas import Action, TradePlan
from aimos.execution.broker.paper import PaperBroker

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _cost():
    return CostModel(taker_bps=7.5, maker_bps=2.0, slip_base_bps=2.0, slip_k=25.0)


def _market_plan():
    return TradePlan(plugin="TrendFollowing", symbol="SOL", action=Action.LONG,
                     entry=150.0, stop_loss=145.0, take_profit=160.0, size_quote=1500.0)


def test_market_order_fills_next_bar_open():
    b = PaperBroker(10_000, _cost())
    b.place(_market_plan())
    # step with a bar → fills at open (next tick)
    b.step("SOL", {"open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0}, TS)
    pos = b.positions()
    assert len(pos) == 1
    assert pos[0].entry == 150.0
    assert pos[0].qty == pytest.approx(1500.0 / 150.0)


def test_take_profit_exit():
    b = PaperBroker(10_000, _cost())
    b.place(_market_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    # next bar reaches TP 160
    b.step("SOL", {"open": 151.0, "high": 161.0, "low": 150.0, "close": 160.0}, TS)
    assert len(b.positions()) == 0  # closed at TP
    assert b.closed_trades_r  # a realized trade recorded
    assert b.closed_trades_r[-1] > 0  # TP → positive R


def test_stop_loss_exit():
    b = PaperBroker(10_000, _cost())
    b.place(_market_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 150.0, "high": 150.5, "low": 144.0, "close": 145.0}, TS)  # hits SL 145
    assert len(b.positions()) == 0
    assert b.closed_trades_r[-1] < 0  # SL → negative R


def test_limit_order_fills_only_when_crossed():
    b = PaperBroker(10_000, _cost())
    plan = TradePlan(plugin="Pullback", symbol="SOL", action=Action.LONG,
                     entry=148.0, stop_loss=145.0, take_profit=160.0, size_quote=1500.0)
    b.place(plan)
    # bar doesn't reach 148 → no fill
    b.step("SOL", {"open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0}, TS)
    assert len(b.positions()) == 0
    # bar crosses 148 → fills at limit
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 147.0, "close": 149.0}, TS)
    assert len(b.positions()) == 1
    assert b.positions()[0].entry == 148.0


def test_equity_reflects_fees():
    b = PaperBroker(10_000, _cost())
    b.place(_market_plan())
    b.step("SOL", {"open": 150.0, "high": 150.0, "low": 150.0, "close": 150.0}, TS)
    # entry fee = 1500 * 7.5bps = 1.125; flat price → equity ~ 10000 - 1.125
    assert b.equity() == pytest.approx(10_000 - 1.125, abs=0.01)


# ---- funding in EV (§23.9B) ----

def test_funding_cost_sign():
    # long paying +5bps/8h over 8h → +5bps cost
    assert funding_cost_bps(5.0, 480.0, 1) == pytest.approx(5.0)
    # long receiving (-5bps) → -5bps (a credit)
    assert funding_cost_bps(-5.0, 480.0, 1) == pytest.approx(-5.0)
    # short flips the sign
    assert funding_cost_bps(5.0, 480.0, -1) == pytest.approx(-5.0)


def test_funding_flips_marginal_ev():
    from aimos.execution.evaluator import expected_value
    # a marginal long: EV ~0 before funding
    base = TradePlan(plugin="TF", symbol="SOL", action=Action.LONG, entry=150.0,
                     stop_loss=145.0, take_profit=160.0, expected_rr=2.0, confidence=0.36)
    model = _cost()
    rb = abs(150 - 145) / 150 * 10_000  # risk_bps
    # +0.05%/8h funding (5bps) added to costs over 8h hold
    base.expected_costs_bps = total_forward_costs_bps(model, 1000, 1e9, funding_rate_bps=5.0,
                                                      hold_minutes=480, direction_sign=1)
    ev_pay = expected_value(base, 1.0)
    base.expected_costs_bps = total_forward_costs_bps(model, 1000, 1e9, funding_rate_bps=-5.0,
                                                      hold_minutes=480, direction_sign=1)
    ev_receive = expected_value(base, 1.0)
    assert ev_receive > ev_pay  # collecting funding improves EV (carry credit)
