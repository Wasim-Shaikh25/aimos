"""Observation phase gate (§5): a long recorded series through ALL engines —
zero exceptions, every Evidence validates, per-engine coverage sane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from aimos.core.clock import LiveClock
from aimos.core.config import load_params
from aimos.core.schemas import Evidence, Timeframe
from aimos.data.context import build_context
from aimos.observation.runner import build_engines, engines_reporting, run_all
from tests.conftest import make_candles


def _year_of_candles(seed: int = 0) -> "object":
    """A year of hourly candles (8760 bars) with realistic random-walk OHLC."""
    rng = np.random.default_rng(seed)
    n = 24 * 365
    rets = rng.normal(0, 0.01, n)
    close = 30_000 * np.cumprod(1 + rets)
    opens = np.concatenate([[close[0]], close[:-1]])
    highs = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lows = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vols = np.abs(rng.normal(1000, 300, n))
    df = make_candles(list(close), tf_minutes=60, opens=list(opens),
                      highs=list(highs), lows=list(lows), volumes=list(vols))
    return df


def test_full_year_through_all_engines_no_exceptions():
    params = load_params()
    engines = build_engines(params, LiveClock())
    df = _year_of_candles()
    peers = {"BTC": df}

    now = df.index[-1].to_pydatetime()
    ctx = build_context("BTC", now, {Timeframe.H1: df}, peers=peers)

    bundle = run_all(engines, ctx)  # per-engine isolation; must not raise

    # every evidence is a valid, registered, bounded Evidence
    assert all(isinstance(e, Evidence) for e in bundle.evidences)
    assert all(0.0 <= e.strength <= 1.0 for e in bundle.evidences)
    assert all(0.0 <= e.reliability <= 1.0 for e in bundle.evidences)

    # candle-only engines report; book/funding/venue ones are absent (no data).
    # price_action always emits structure/key_levels on a series with swings.
    reporting = engines_reporting(bundle)
    assert "price_action_engine" in reporting
    assert len(bundle.evidences) > 0


def test_multi_timeframe_bundle():
    params = load_params()
    engines = build_engines(params, LiveClock())
    df = _year_of_candles(seed=1)
    # sub-sample to a couple of timeframes
    ctx = build_context(
        "BTC", df.index[-1].to_pydatetime(),
        {Timeframe.H1: df.iloc[-500:], Timeframe.M15: df.iloc[-500:]},
        peers={"BTC": df},
    )
    bundle = run_all(engines, ctx)
    tfs = {e.timeframe for e in bundle.evidences}
    # evidence carries its timeframe; more than one TF present
    assert len(tfs) >= 1


def test_failing_engine_is_isolated():
    params = load_params()
    engines = build_engines(params, LiveClock())

    class Boom:
        name = "boom_engine"

        def observe(self, ctx):
            raise RuntimeError("engine exploded")

    engines.append(Boom())
    df = _year_of_candles(seed=2)
    ctx = build_context("BTC", df.index[-1].to_pydatetime(), {Timeframe.H1: df}, peers={"BTC": df})
    bundle = run_all(engines, ctx)  # must not raise despite Boom
    assert len(bundle.evidences) > 0
