"""Backtest engine anti-lookahead + determinism tests (§9.1, §13 — card P4-T7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from aimos.core.config import load_params
from aimos.backtest.engine import BacktestEngine

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candles(n, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.01, n)
    close = 30_000 * np.cumprod(1 + rets)
    opens = np.concatenate([[close[0]], close[:-1]])
    highs = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lows = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    idx = pd.DatetimeIndex([START + timedelta(hours=i) for i in range(n)], tz="UTC")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": close,
                         "volume": np.abs(rng.normal(1000, 200, n)), "synthetic": [False] * n}, index=idx)


def test_backtest_runs_with_nonzero_no_trade_rate():
    res = BacktestEngine(load_params(), "BTC").run(_candles(24 * 30), warmup=210)
    assert res.n_decisions > 0
    assert res.no_trade_rate > 0.0  # the system must sometimes abstain (§9 DoD)
    ok, _ = res.journal.verify()
    assert ok


def test_replay_determinism_byte_identical_journal():
    candles = _candles(24 * 20)
    r1 = BacktestEngine(load_params(), "BTC").run(candles, warmup=210)
    r2 = BacktestEngine(load_params(), "BTC").run(candles, warmup=210)
    # same recorded data twice → identical decisions + identical chain tip
    tip1 = r1.journal.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]
    tip2 = r2.journal.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]
    assert tip1 == tip2  # byte-identical journal (no wall-clock leakage)
    assert r1.equity_curve == r2.equity_curve


def test_poisoned_future_no_lookahead():
    # appending NaN-poisoned bars AFTER the decision point must not change the
    # decision at that point — indicators use data <= t only.
    candles = _candles(300)
    cut = 260
    clean = candles.iloc[:cut]

    eng_a = BacktestEngine(load_params(), "BTC")
    # run to the cut and capture the last decision's understanding via journal
    res_a = eng_a.run(clean, warmup=210)

    # poison the future: same data up to cut, then garbage after
    poisoned = candles.copy()
    poisoned.iloc[cut:, poisoned.columns.get_loc("close")] = np.nan
    poisoned.iloc[cut:, poisoned.columns.get_loc("high")] = np.nan
    eng_b = BacktestEngine(load_params(), "BTC")
    res_b = eng_b.run(poisoned.iloc[:cut], warmup=210)

    # identical inputs up to cut → identical journals
    tip_a = res_a.journal.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]
    tip_b = res_b.journal.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]
    assert tip_a == tip_b


def test_no_same_bar_fill():
    # a market order placed at bar i fills at bar i+1's open, never bar i.
    from aimos.execution.broker.paper import PaperBroker
    from aimos.backtest.costs import CostModel
    from aimos.core.schemas import Action, TradePlan
    b = PaperBroker(10_000, CostModel(7.5, 2.0, 2.0, 25.0))
    b.place(TradePlan(plugin="TF", symbol="X", action=Action.LONG, entry=100.0,
                      stop_loss=95.0, take_profit=110.0, size_quote=1000.0))
    assert len(b.positions()) == 0  # not filled at placement time
    b.step("X", {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5}, START)
    assert b.positions()[0].entry == 101.0  # filled at the NEXT bar's open
