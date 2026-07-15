"""Candle service tests (§4.1 — card P1-T2 DoD).

No network: a recorded ``FakeFetcher`` serves rows from an in-memory series.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from aimos.data.candles import (
    CandleStore,
    fetch_candles,
    gap_fill,
    has_gaps,
    resample,
)

START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def _series(n: int, tf_minutes: int, drop: set[int] | None = None) -> list[list[float]]:
    """Build ``n`` hourly-ish rows; ``drop`` removes indices to create gaps."""
    drop = drop or set()
    rows = []
    price = 100.0
    for i in range(n):
        if i in drop:
            continue
        ts = START + timedelta(minutes=tf_minutes * i)
        ts_ms = int(ts.timestamp() * 1000)
        o = price
        c = price + 1
        rows.append([ts_ms, o, price + 2, price - 1, c, 10.0 + i])
        price = c
    return rows


class FakeFetcher:
    """Serves recorded rows with ts >= since, ascending, up to limit."""

    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = sorted(rows, key=lambda r: r[0])
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.calls += 1
        out = [r for r in self.rows if since is None or r[0] >= since]
        return out[:limit]


def test_gap_fill_flags_synthetic():
    # 10 hourly rows with the 4th and 5th missing.
    rows = _series(10, 60, drop={4, 5})
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.drop(columns=["ts_ms"])

    filled = gap_fill(df, "1h")
    assert len(filled) == 10  # grid completed
    assert filled["synthetic"].sum() == 2  # two gaps flagged
    synth = filled[filled["synthetic"]]
    # synthetic bars: OHLC all equal to carried close, volume zero
    for _, bar in synth.iterrows():
        assert bar["open"] == bar["high"] == bar["low"] == bar["close"]
        assert bar["volume"] == 0.0
    assert not has_gaps(filled, "1h")


def test_resample_matches_pandas_reference():
    rows = _series(60, 1)  # 60 one-minute candles
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.drop(columns=["ts_ms"])

    out = resample(df, "5m")
    # reference: hand-built pandas aggregation
    ref = df.resample("5min").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna(subset=["open"])
    pd.testing.assert_frame_equal(out, ref)
    assert len(out) == 12  # 60 → 12 five-minute bars


def test_fetch_candles_produces_gapless_frame():
    rows = _series(200, 60, drop={50, 51, 120})  # gaps in the middle
    fetcher = FakeFetcher(rows)
    end = START + timedelta(hours=199)
    df = fetch_candles(fetcher, "BTC/USDT", "1h", depth=200, until=end, page_limit=50)

    assert not has_gaps(df, "1h")
    assert df["synthetic"].sum() == 3  # the three dropped bars synthesized
    assert df.index.tz is not None  # UTC-aware
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "synthetic"]


def test_store_round_trip_and_dedup(tmp_path):
    rows = _series(30, 60)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.drop(columns=["ts_ms"])
    df = gap_fill(df, "1h")

    store = CandleStore(tmp_path)
    store.write("binance", "BTC/USDT", "1h", df.iloc[:20])
    store.write("binance", "BTC/USDT", "1h", df.iloc[15:])  # overlapping append

    out = store.read("binance", "BTC/USDT", "1h")
    assert len(out) == 30  # overlap deduped, not duplicated
    assert out.index.is_monotonic_increasing
    assert not out.index.has_duplicates
    # nested path layout data/{exchange}/{symbol}/{tf}.parquet
    assert store.path_for("binance", "BTC/USDT", "1h").name == "1h.parquet"


def test_fetch_empty_source_returns_empty():
    df = fetch_candles(FakeFetcher([]), "BTC/USDT", "1h", depth=10, until=START)
    assert df.empty
    assert "synthetic" in df.columns
