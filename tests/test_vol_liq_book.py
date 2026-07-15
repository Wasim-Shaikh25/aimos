"""Volatility + Liquidity + OrderBook tests (§5.4-5.6 — card P2-T4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aimos.core.clock import LiveClock
from aimos.core.schemas import BookAggregate, Direction, Timeframe
from aimos.data.context import build_context
from aimos.data.orderbook import detect_walls, simulate_market_order
from aimos.observation.liquidity import LiquidityEngine
from aimos.observation.orderbook_engine import OrderBookEngine
from aimos.observation.volatility import VolatilityEngine
from tests.conftest import make_candles, obs_cfg, reliability

TS = datetime(2026, 1, 2, tzinfo=timezone.utc)


# ---- volatility ----

def _vol_observe(df):
    eng = VolatilityEngine(obs_cfg(), LiveClock(), reliability("volatility"))
    ctx = build_context("BTC", df.index[-1].to_pydatetime(), {Timeframe.H1: df})
    return eng.observe(ctx)


def test_vol_compression_detected():
    n = 120
    closes = [100.0] * n
    # volatile first 100 bars, calm last 20 → ATR14/ATR100 < 0.6
    highs = [110.0 if i < 100 else 100.25 for i in range(n)]
    lows = [90.0 if i < 100 else 99.75 for i in range(n)]
    df = make_candles(closes, highs=highs, lows=lows)
    names = {e.name for e in _vol_observe(df)}
    assert "vol_compression" in names


def test_vol_shock_detected():
    n = 120
    closes = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    highs[-1] = 130.0  # last bar TR huge → > 3×ATR
    lows[-1] = 99.0
    df = make_candles(closes, highs=highs, lows=lows)
    shock = [e for e in _vol_observe(df) if e.name == "vol_shock"]
    assert shock
    assert shock[0].direction == Direction.NEUTRAL
    assert shock[0].meta.get("risk_gate") is True


# ---- slippage sim (hand-computed book) ----

def test_slippage_sim_vs_hand_computed():
    mid = 99.5
    asks = [[100.0, 1.0], [101.0, 2.0], [102.0, 5.0]]
    slip = simulate_market_order(asks, size_usd=250.0, mid=mid)
    # fill 100usd @100 (1 base) + 150usd @101 (150/101 base)
    filled = 1.0 + 150.0 / 101.0
    vwap = 250.0 / filled
    expected = abs(vwap - mid) / mid * 10_000.0
    assert slip == pytest.approx(expected)


def test_slippage_grows_with_size():
    asks = [[100.0, 1.0], [101.0, 1.0], [110.0, 100.0]]
    small = simulate_market_order(asks, 50.0, 99.5)
    big = simulate_market_order(asks, 500.0, 99.5)
    assert big > small


# ---- wall detection with spoof flag ----

def test_detect_walls_with_spoof_flag():
    mid = 100.0
    levels = [[99.5, 1.0], [99.6, 1.0], [99.7, 20.0], [99.8, 1.0]]
    walls = detect_walls(levels, mid, within_pct=1.0, size_mult=5.0,
                         age_seconds={99.7: 30.0}, spoof_age_seconds=60.0)
    assert len(walls) == 1
    assert walls[0]["price"] == 99.7
    assert walls[0]["spoof_suspect"] is True  # appeared 30s ago < 60s


def test_detect_walls_none_when_uniform():
    levels = [[99.5, 1.0], [99.6, 1.0], [99.7, 1.0]]
    assert detect_walls(levels, 100.0, 1.0, 5.0) == []


# ---- orderbook + liquidity engines from aggregates ----

def _book_window(imbalances, spreads=None, depths=None):
    spreads = spreads or [2.0] * len(imbalances)
    depths = depths or [1_000_000.0] * len(imbalances)
    out = []
    for i, imb in enumerate(imbalances):
        out.append(BookAggregate(
            timestamp=TS + timedelta(minutes=i), best_bid=99.9, best_ask=100.1,
            spread_bps=spreads[i], bid_depth_usd=depths[i] * (1 + imb) / 2,
            ask_depth_usd=depths[i] * (1 - imb) / 2, imbalance=imb,
        ))
    return out


def test_orderbook_imbalance_evidence():
    eng = OrderBookEngine(obs_cfg(), LiveClock(), reliability("orderbook"))
    window = _book_window([0.4] * 30)
    ctx = build_context("BTC", window[-1].timestamp, {}, orderbook_window=window)
    evs = eng.observe(ctx)
    imb = [e for e in evs if e.name == "book_imbalance"]
    assert imb and imb[0].direction == Direction.BULLISH
    assert imb[0].strength == pytest.approx(0.4)


def test_liquidity_thin_book_and_spread():
    eng = LiquidityEngine(obs_cfg(), LiveClock(), reliability("liquidity"))
    # last snapshot: wide spread + shallow depth
    spreads = [2.0] * 40 + [20.0]
    depths = [1_000_000.0] * 40 + [10_000.0]
    window = _book_window([0.0] * 41, spreads=spreads, depths=depths)
    ctx = build_context("BTC", window[-1].timestamp, {}, orderbook_window=window)
    names = {e.name for e in eng.observe(ctx)}
    assert "thin_book" in names
    assert "spread" in names
    assert "slippage_estimate" in names
