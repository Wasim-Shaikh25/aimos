"""Trade manager tests (§23.1, §23.10C — card P4-T4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from aimos.core.config import load_params
from aimos.core.schemas import Action, Behavior, Direction, Position, Regime
from aimos.execution.trade_manager import ManagementState, TradeManager
from tests.conftest import make_mu

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _tm():
    return TradeManager(load_params().trade_manager.model_dump())


def _pos(entry=150.0, stop=145.0, side=Action.LONG):
    return Position(symbol="SOL", venue="paper", side=side, qty=1.0, entry=entry,
                    stop=stop, tp=170.0, opened_at=TS, plugin="TrendFollowing",
                    decision_id="SOL-1", mode_tag="swing")


def _state(entry=150.0, stop=145.0, hold=240):
    return ManagementState(initial_risk=entry - stop, current_stop=stop, expected_hold_minutes=hold)


def test_breakeven_moves_stop_to_entry():
    tm = _tm()
    pos, st = _pos(), _state()
    # +1.0R → price 155 (risk 5)
    events = tm.step(pos, 155.0, atr=2.0, mu=None, now=TS + timedelta(minutes=5), state=st)
    kinds = [e.kind for e in events]
    assert "breakeven" in kinds
    assert st.current_stop == 150.0  # moved to entry


def test_partial_tp_at_threshold():
    tm = _tm()
    pos, st = _pos(), _state()
    events = tm.step(pos, 157.5, atr=2.0, mu=None, now=TS + timedelta(minutes=5), state=st)
    partials = [e for e in events if e.kind == "partial_tp"]
    assert partials and partials[0].closed_qty == 0.4  # 40% of qty 1.0


def test_trail_never_widens():
    tm = _tm()
    pos, st = _pos(), _state()
    # activate trail at +1.5R (price 157.5), then price rises then falls
    tm.step(pos, 165.0, atr=2.0, mu=None, now=TS + timedelta(minutes=5), state=st)
    high_stop = st.current_stop
    # price falls to 160 → trailing stop must NOT move down
    tm.step(pos, 160.0, atr=2.0, mu=None, now=TS + timedelta(minutes=10), state=st)
    assert st.current_stop >= high_stop  # never widens


def test_thesis_exit_on_regime_flip():
    tm = _tm()
    pos, st = _pos(), _state()
    mu = make_mu(direction_bias=Direction.BEARISH, confidence=0.6)  # flipped against long
    events = tm.step(pos, 151.0, atr=2.0, mu=mu, now=TS + timedelta(minutes=5), state=st)
    assert any(e.kind == "thesis_exit" for e in events)


def test_thesis_exit_on_crash():
    tm = _tm()
    events = tm.step(_pos(), 151.0, atr=2.0, mu=make_mu(regime=Regime.CRASH),
                     now=TS + timedelta(minutes=5), state=_state())
    assert any(e.kind == "thesis_exit" for e in events)


def test_time_stop_fires():
    tm = _tm()
    pos, st = _pos(), _state(hold=60)
    # held 3h (>2×60min) with < +0.3R (price flat ~150.3)
    late = TS + timedelta(hours=3)
    events = tm.step(pos, 150.3, atr=2.0, mu=None, now=late, state=st)
    assert any(e.kind == "time_stop" for e in events)


def test_liquidity_tighten_on_degrade():
    tm = _tm()
    events = tm.step(_pos(), 151.0, atr=2.0, mu=None, now=TS + timedelta(minutes=5),
                     state=_state(), exit_slippage_bps=50.0, entry_exit_slippage_bps=10.0)
    assert any(e.kind == "liquidity_tighten" for e in events)


@settings(max_examples=50)
@given(prices=st.lists(st.floats(min_value=151, max_value=200), min_size=2, max_size=20))
def test_trail_monotonic_property(prices):
    tm = _tm()
    pos, st = _pos(), _state()
    last_stop = st.current_stop
    now = TS
    for i, p in enumerate(prices):
        now = TS + timedelta(minutes=5 * (i + 1))
        tm.step(pos, p, atr=2.0, mu=None, now=now, state=st)
        assert st.current_stop >= last_stop  # long trail only tightens
        last_stop = st.current_stop
