"""Normalization, indicators, base + context tests (§5.0, §25.1 — card P2-T1)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from aimos.core import indicators as ind
from aimos.core.normalize import ratio_to_strength, z_to_strength
from aimos.core.schemas import Timeframe
from aimos.data.context import build_context
from aimos.observation.base import real_candles
from tests.conftest import make_candles

TS = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_z_to_strength_saturates():
    assert z_to_strength(0.0, 3.0) == 0.0
    assert z_to_strength(1.5, 3.0) == pytest.approx(0.5)
    assert z_to_strength(4.0, 3.0) == 1.0  # saturates
    with pytest.raises(ValueError):
        z_to_strength(1.0, 0.0)


def test_ratio_to_strength():
    assert ratio_to_strength(1.0, 1.0, 3.0) == 0.0  # neutral
    assert ratio_to_strength(2.0, 1.0, 3.0) == pytest.approx(0.5)
    assert ratio_to_strength(5.0, 1.0, 3.0) == 1.0  # saturates


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.linspace(100, 200, 100))  # monotonic up → RSI high
    down = pd.Series(np.linspace(200, 100, 100))
    assert ind.rsi(up, 14).iloc[-1] > 70
    assert ind.rsi(down, 14).iloc[-1] < 30


def test_atr_positive():
    df = make_candles([100 + i for i in range(50)])
    a = ind.atr(df, 14).iloc[-1]
    assert a > 0


def test_beta_and_correlation():
    m = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    a = 2.0 * m  # perfectly correlated, beta 2
    assert ind.beta(a, m) == pytest.approx(2.0)
    assert ind.correlation(a, m) == pytest.approx(1.0)


def test_real_candles_excludes_synthetic():
    df = make_candles([100, 101, 102, 103], synthetic=[False, True, False, True])
    assert len(real_candles(df)) == 2


def test_build_context_trims_to_now():
    df = make_candles([100 + i for i in range(10)])
    now = df.index[5].to_pydatetime()
    ctx = build_context("BTC", now, {Timeframe.H1: df})
    assert ctx.candles[Timeframe.H1].index.max() <= now
    assert len(ctx.candles[Timeframe.H1]) == 6  # bars 0..5
