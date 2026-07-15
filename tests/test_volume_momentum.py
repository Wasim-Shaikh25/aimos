"""Volume + Momentum engine tests (§5.2-5.3 — card P2-T3)."""

from __future__ import annotations

import numpy as np
import pytest

from aimos.core.clock import LiveClock
from aimos.core.schemas import Direction, Timeframe
from aimos.data.context import build_context
from aimos.observation.momentum import MomentumEngine
from aimos.observation.volume import VolumeEngine
from tests.conftest import make_candles, obs_cfg, reliability


def _observe(engine, df, tf=Timeframe.H1):
    ctx = build_context("BTC", df.index[-1].to_pydatetime(), {tf: df})
    return engine.observe(ctx)


# ---- volume ----

def _vol_engine():
    return VolumeEngine(obs_cfg(), LiveClock(), reliability("volume"))


def test_volume_spike_strength_exact():
    # 30 bars baseline vol 100, last bar 300 → rel_vol 3.0
    closes = [100 + i for i in range(30)]  # bullish candles (close>open)
    vols = [100.0] * 29 + [300.0]
    df = make_candles(closes, volumes=vols)
    evs = _observe(_vol_engine(), df)
    spike = [e for e in evs if e.name == "volume_spike"]
    assert spike
    # SMA(vol,20) includes the last bar: (19·100 + 300)/20 = 110 → rel_vol = 300/110
    rel_vol = 300.0 / 110.0
    expected = abs(rel_vol - 1.0) / (4.0 - 1.0)  # ratio_to_strength(rel_vol, 1, cap=4)
    assert spike[0].strength == pytest.approx(expected, abs=0.01)
    assert spike[0].direction == Direction.BULLISH


def test_synthetic_candles_excluded_from_volume():
    # last (real) bar has normal volume; a synthetic bar with huge volume must
    # be ignored, so no spike from the synthetic bar.
    closes = [100 + i for i in range(30)] + [131]
    vols = [100.0] * 30 + [9999.0]
    synth = [False] * 30 + [True]
    df = make_candles(closes, volumes=vols, synthetic=synth)
    evs = _observe(_vol_engine(), df)
    # the synthetic huge-volume bar is dropped → last real bar vol ~100 → no spike
    assert not [e for e in evs if e.name == "volume_spike"]


def test_absorption_opposite_prior_move():
    # strong prior up-move, then a high-volume tiny-body bar → bearish absorption
    closes = list(range(100, 130)) + [129.9]  # last bar barely moves after up-run
    opens = closes[:]
    opens[-1] = 129.85
    vols = [100.0] * 30 + [400.0]
    df = make_candles(closes, opens=opens, volumes=vols,
                      highs=[c + 0.2 for c in closes], lows=[c - 0.2 for c in closes])
    evs = _observe(_vol_engine(), df)
    absorption = [e for e in evs if e.name == "absorption"]
    assert absorption and absorption[0].direction == Direction.BEARISH


# ---- momentum ----

def _mom_engine():
    return MomentumEngine(obs_cfg(), LiveClock(), reliability("momentum"))


def test_rsi_overbought_bearish():
    closes = list(np.linspace(100, 250, 130))  # strong uptrend → RSI > 70
    df = make_candles(closes)
    evs = _observe(_mom_engine(), df)
    ob = [e for e in evs if e.name == "rsi_overbought"]
    assert ob and ob[0].direction == Direction.BEARISH


def test_rsi_oversold_bullish():
    closes = list(np.linspace(250, 100, 130))  # strong downtrend → RSI < 30
    df = make_candles(closes)
    evs = _observe(_mom_engine(), df)
    os_ = [e for e in evs if e.name == "rsi_oversold"]
    assert os_ and os_[0].direction == Direction.BULLISH


def test_ema_slope_direction():
    closes = list(np.linspace(100, 200, 130))  # rising → positive EMA slope
    df = make_candles(closes)
    evs = _observe(_mom_engine(), df)
    slope = [e for e in evs if e.name == "ema_slope"]
    assert slope and slope[0].direction == Direction.BULLISH


def test_momentum_evidence_bounded():
    closes = list(np.linspace(100, 130, 130))
    for e in _observe(_mom_engine(), make_candles(closes)):
        assert 0.0 <= e.strength <= 1.0
