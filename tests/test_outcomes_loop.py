"""T-001 — close the measurement loop: PaperBroker outcomes → journal (§8.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from aimos.backtest import costs as cost_mod
from aimos.backtest.engine import BacktestEngine
from aimos.core.config import load_params
from aimos.core.schemas import Action, OutcomeRecord, TradePlan
from aimos.execution.broker.paper import PaperBroker
from aimos.journal.journal import Journal
from aimos.runtime.pipeline import PipelineOrchestrator
from tests.conftest import make_candles

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _cost():
    return cost_mod.CostModel(taker_bps=7.5, maker_bps=2.0, slip_base_bps=2.0, slip_k=25.0)


def _long_plan():
    return TradePlan(
        plugin="TrendFollowing", symbol="SOL", action=Action.LONG,
        entry=150.0, stop_loss=145.0, take_profit=160.0, size_quote=1500.0,
    )


def test_long_hits_take_profit():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 151.0, "high": 161.0, "low": 150.0, "close": 160.0}, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    oc = outcomes[0]
    assert oc.exit_reason == "tp"
    assert oc.pnl_r > 0
    assert oc.pnl_r == pytest.approx(b.closed_trades_r[-1])
    assert oc.max_favorable_r >= oc.pnl_r
    assert oc.max_adverse_r <= 0


def test_long_hits_stop_loss():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 150.0, "high": 150.5, "low": 144.0, "close": 145.0}, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    oc = outcomes[0]
    assert oc.exit_reason == "sl"
    assert oc.pnl_r < -0.99
    assert oc.pnl_r == pytest.approx(b.closed_trades_r[-1])
    assert oc.max_adverse_r < 0
    assert oc.max_favorable_r >= 0


def test_short_hits_take_profit():
    plan = TradePlan(
        plugin="TrendFollowing", symbol="SOL", action=Action.SHORT,
        entry=150.0, stop_loss=155.0, take_profit=140.0, size_quote=1500.0,
    )
    b = PaperBroker(10_000, _cost())
    b.place(plan)
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.0, "close": 150.0}, TS)
    b.step("SOL", {"open": 151.0, "high": 151.0, "low": 139.0, "close": 140.0}, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    oc = outcomes[0]
    assert oc.exit_reason == "tp"
    assert oc.pnl_r > 0
    assert oc.pnl_r == pytest.approx(b.closed_trades_r[-1])
    assert oc.max_favorable_r > 0
    assert oc.max_adverse_r <= 0


def test_open_position_produces_no_outcome():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)

    assert len(b.drain_outcomes()) == 0
    assert len(b.closed_trades_r) == 0


def test_mae_mfe_tracked_across_five_bars():
    plan = TradePlan(
        plugin="TrendFollowing", symbol="SOL", action=Action.LONG,
        entry=100.0, stop_loss=90.0, take_profit=105.0, size_quote=1000.0,
    )
    b = PaperBroker(10_000, _cost())
    b.place(plan)

    bars = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 103.0, "low": 98.0, "close": 102.0},
        {"open": 102.0, "high": 101.0, "low": 97.0, "close": 100.0},
        {"open": 100.0, "high": 104.0, "low": 96.0, "close": 103.0},
        {"open": 103.0, "high": 103.0, "low": 95.0, "close": 99.0},
        {"open": 99.0, "high": 105.0, "low": 99.0, "close": 104.0},
    ]
    for bar in bars:
        b.step("SOL", bar, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    oc = outcomes[0]
    assert oc.exit_reason == "tp"
    assert oc.max_adverse_r == pytest.approx(-0.5)
    assert oc.max_favorable_r == pytest.approx(0.5)


def test_same_bar_sl_and_tp_sl_wins():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 151.0, "high": 161.0, "low": 144.0, "close": 150.0}, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    oc = outcomes[0]
    assert oc.exit_reason == "sl"
    assert oc.max_adverse_r == pytest.approx(-1.2)
    assert oc.max_favorable_r == pytest.approx(2.2)


def test_hash_chain_survives_ten_outcome_writes():
    j = Journal(":memory:")
    for i in range(10):
        j.write_outcome(OutcomeRecord(
            decision_id=f"SOL-{i}", exit_time=TS, exit_price=150.0 + i,
            pnl_r=0.1 * i, pnl_quote=10.0 * i, max_adverse_r=-0.1, max_favorable_r=0.2,
            exit_reason="tp" if i % 2 == 0 else "sl",
        ))

    ok, broken = j.verify()
    assert ok and broken is None


def test_drain_outcomes_is_empty_after_second_call():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 151.0, "high": 161.0, "low": 150.0, "close": 160.0}, TS)

    assert len(b.drain_outcomes()) == 1
    assert b.drain_outcomes() == []


def test_backtest_writes_outcomes_and_journal_verifies():
    candles = make_candles(list(range(50, 110)), start=TS, tf_minutes=60)
    engine = BacktestEngine(load_params(), "SOL", journal_path=":memory:")
    result = engine.run(candles, warmup=20)

    ok, _ = result.journal.verify()
    assert ok
    rows = result.journal.conn.execute("SELECT COUNT(*) c FROM outcomes").fetchone()["c"]
    assert isinstance(rows, int)


def test_paper_and_backtest_produce_identical_outcome_rows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex(
        [start + pd.Timedelta(hours=i) for i in range(30)], tz="UTC", name="timestamp"
    )
    base = 30_000.0
    flat = [{"open": base, "high": base + 100, "low": base - 100, "close": base,
             "volume": 1000.0, "synthetic": False} for _ in range(26)]
    last = [
        {"open": base, "high": base + 100, "low": base - 100, "close": base,
         "volume": 1000.0, "synthetic": False},
        {"open": base, "high": base + 100, "low": base - 100, "close": base,
         "volume": 1000.0, "synthetic": False},
        {"open": base, "high": base + 100, "low": base - 100, "close": base,
         "volume": 1000.0, "synthetic": False},
        {"open": base, "high": 31_100.0, "low": base, "close": 31_000.0,
         "volume": 1000.0, "synthetic": False},
    ]
    candles = pd.DataFrame(flat + last, index=idx)

    plan = TradePlan(
        plugin="TrendFollowing", symbol="BTC", action=Action.LONG,
        entry=base, stop_loss=base - 1000.0, take_profit=31_000.0, size_quote=3000.0,
    )

    engine = BacktestEngine(load_params(), "BTC", starting_equity=10_000.0, journal_path=":memory:")
    placed = False

    def fixed_decide(*_args, **_kwargs):
        nonlocal placed
        if placed:
            return TradePlan(plugin="TrendFollowing", symbol="BTC", action=Action.NO_TRADE)
        placed = True
        return plan

    engine.execution.decide = fixed_decide  # type: ignore[assignment]
    engine.run(candles, warmup=25)

    back_outcome = _outcome_from_journal(engine.journal)

    b = PaperBroker(10_000.0, engine.cost)
    b.place(plan)
    for i in range(26, 30):
        b.step("BTC", candles.iloc[i].to_dict(), candles.index[i].to_pydatetime())
    manual_outcomes = b.drain_outcomes()

    assert len(manual_outcomes) == 1
    assert back_outcome is not None
    assert manual_outcomes[0].model_dump(mode="json") == back_outcome.model_dump(mode="json")


def _outcome_from_journal(journal: Journal) -> OutcomeRecord | None:
    row = journal.conn.execute("SELECT payload FROM outcomes LIMIT 1").fetchone()
    if row is None:
        return None
    return OutcomeRecord.model_validate_json(row["payload"])


def test_pnl_r_matches_closed_trades_r():
    b = PaperBroker(10_000, _cost())
    b.place(_long_plan())
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5}, TS)
    b.step("SOL", {"open": 151.0, "high": 161.0, "low": 150.0, "close": 160.0}, TS)

    oc = b.drain_outcomes()[0]
    assert oc.pnl_r == pytest.approx(b.closed_trades_r[-1])


def test_zero_initial_risk_quote_does_not_crash():
    plan = TradePlan(
        plugin="TrendFollowing", symbol="SOL", action=Action.LONG,
        entry=150.0, stop_loss=150.0, take_profit=160.0, size_quote=1500.0,
    )
    b = PaperBroker(10_000, _cost())
    b.place(plan)
    b.step("SOL", {"open": 150.0, "high": 151.0, "low": 149.9, "close": 150.5}, TS)

    outcomes = b.drain_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].pnl_r == 0.0
    assert outcomes[0].max_adverse_r == 0.0
    assert outcomes[0].max_favorable_r == 0.0


class _RaisingJournal(Journal):
    def write_outcome(self, record: OutcomeRecord) -> str:
        raise RuntimeError("disk full")


class _FakeBroker:
    def __init__(self, outcomes: list[OutcomeRecord]) -> None:
        self._outcomes = outcomes

    def drain_outcomes(self) -> list[OutcomeRecord]:
        out = self._outcomes
        self._outcomes = []
        return out


def test_journal_write_failure_does_not_crash_flush():
    oc = OutcomeRecord(
        decision_id="SOL-1", exit_time=TS, exit_price=150.0,
        pnl_r=1.0, pnl_quote=10.0, max_adverse_r=-0.1, max_favorable_r=0.2,
        exit_reason="tp",
    )
    orch = PipelineOrchestrator(load_params(), journal=_RaisingJournal(":memory:"))
    orch.flush_broker_outcomes(_FakeBroker([oc]))

    assert orch.journal.decision_count() == 0
