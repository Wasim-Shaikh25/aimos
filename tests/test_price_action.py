"""Price Action engine tests (§5.1 — card P2-T2)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from aimos.core.clock import LiveClock
from aimos.core.schemas import Direction, Timeframe
from aimos.data.context import build_context
from aimos.observation.price_action import PriceActionEngine, find_swings
from tests.conftest import make_candles, obs_cfg, reliability


def _engine():
    return PriceActionEngine(obs_cfg(), LiveClock(), reliability("price_action"))


def _observe(df):
    ctx = build_context("BTC", df.index[-1].to_pydatetime(), {Timeframe.H1: df})
    return _engine().observe(ctx)


def test_find_swings_no_lookahead():
    # a clear peak at index 5; k=3 → confirmed. A peak at the last bar must NOT
    # be reported (needs k future bars).
    closes = [10, 11, 12, 20, 12, 11, 10, 11, 12, 13, 30]  # last bar is highest
    df = make_candles(closes, highs=[c + 0.5 for c in closes], lows=[c - 0.5 for c in closes])
    highs, lows = find_swings(df, k=3)
    assert (len(df) - 1) not in highs  # last bar never a confirmed swing
    assert 3 in highs  # the interior peak at index 3 is confirmed


def _rising_wave(cycles=6):
    """Rising triangular wave: one clean peak per 10-bar cycle, strictly higher
    highs and higher lows each cycle (k=3 swings confirm cleanly)."""
    closes = []
    base = 100.0
    for _ in range(cycles):
        closes += [base, base + 2, base + 4, base + 6, base + 8,
                   base + 10, base + 8, base + 6, base + 4, base + 2]
        base += 6
    return closes


def _tight(closes):
    return make_candles(closes, highs=[c + 0.1 for c in closes], lows=[c - 0.1 for c in closes])


def test_structure_trend_bullish_on_hh_hl():
    closes = _rising_wave()
    df = _tight(closes)
    evs = _observe(df)
    structure = [e for e in evs if e.name == "structure_trend" and e.strength > 0]
    assert structure and structure[0].direction == Direction.BULLISH
    # key_levels ride in the structure evidence meta
    assert "key_levels" in structure[0].meta


def test_bos_bullish_breakout():
    # rising wave, then a decisive breakout bar above the last swing high
    closes = _rising_wave() + [300.0]
    df = _tight(closes)
    evs = _observe(df)
    bos = [e for e in evs if e.name == "bos"]
    assert bos and bos[0].direction == Direction.BULLISH


def test_range_bound_detected():
    # tight oscillation → range_bound NEUTRAL
    closes = [100 + (i % 2) for i in range(60)]  # 100/101 oscillation
    df = make_candles(closes, highs=[101.2] * 60, lows=[99.8] * 60)
    evs = _observe(df)
    rb = [e for e in evs if e.name == "range_bound"]
    assert rb and rb[0].direction == Direction.NEUTRAL


def test_all_evidence_registered_and_bounded():
    df = make_candles(list(range(10, 80)))
    for e in _observe(df):
        assert 0.0 <= e.strength <= 1.0
