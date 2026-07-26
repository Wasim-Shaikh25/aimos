#!/usr/bin/env python
"""Download 12 months of Binance historical klines and store as parquet.

This is a convenience tool for building the offline dataset used by the ML
training pipeline and regression tests. It uses only free, public Binance Vision
monthly kline archives and writes deduplicated parquet via ``CandleStore``.

Examples:
    python -m scripts.download_history --symbol BTC/USDT --timeframe 1h --months 12
    python -m scripts.download_history --symbol BTC/USDT,ETH/USDT --timeframe 1h

"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from aimos.data.candles import CandleStore


_VISION_URL = "https://data.binance.vision/data/spot/monthly/klines"
_BINANCE_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "qav", "trades", "tbav", "tqav", "ignore",
]


def _binance_pair(symbol: str) -> str:
    """Convert ``BTC/USDT`` to ``BTCUSDT`` for Binance Vision filenames."""
    return symbol.replace("/", "").upper()


def _month_range(months: int) -> list[tuple[int, int]]:
    """Return the last ``months`` (year, month) pairs ending at last month UTC."""
    now = datetime.now(timezone.utc)
    # start at last completed month
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    pairs: list[tuple[int, int]] = []
    for _ in range(months):
        pairs.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    pairs.reverse()
    return pairs


def _to_timeframe(tf: str) -> str:
    """Map project Timeframe enum values to Binance interval strings."""
    mapping = {
        "M1": "1m", "M5": "5m", "M15": "15m",
        "H1": "1h", "H4": "4h", "D1": "1d",
    }
    return mapping.get(tf, tf)


def _read_zip_csv(raw: bytes) -> pd.DataFrame:
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            df = pd.read_csv(f, header=None, names=_BINANCE_KLINE_COLS)
    # Binance Vision monthly archives use microsecond timestamps.
    df.index = pd.to_datetime(df["open_time"], unit="us", utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


async def _download_month(
    client: httpx.AsyncClient,
    url: str,
    pair: str,
    year: int,
    month: int,
) -> tuple[int, int, pd.DataFrame | None]:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        df = _read_zip_csv(resp.content)
        return year, month, df
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"  {pair} {year}-{month:02d}: not available yet (404)")
        else:
            print(f"  {pair} {year}-{month:02d}: HTTP {e.response.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"  {pair} {year}-{month:02d}: error {e}")
    return year, month, None


async def _download_symbol(
    client: httpx.AsyncClient,
    store: CandleStore,
    exchange: str,
    symbol: str,
    timeframe: str,
    months: int,
) -> int:
    pair = _binance_pair(symbol)
    interval = _to_timeframe(timeframe)
    pairs = _month_range(months)
    tasks = [
        _download_month(
            client,
            f"{_VISION_URL}/{pair}/{interval}/{pair}-{interval}-{y}-{m:02d}.zip",
            pair, y, m,
        )
        for y, m in pairs
    ]
    frames: list[pd.DataFrame] = []
    for coro in asyncio.as_completed(tasks):
        _, _, df = await coro
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        print(f"{symbol}: no data downloaded")
        return 0

    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    path = store.write(exchange, symbol, timeframe, combined)
    print(f"{symbol}: wrote {len(combined)} rows to {path}")
    return len(combined)


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download Binance historical klines to data/")
    ap.add_argument("--exchange", default="binance", help="exchange name for CandleStore")
    ap.add_argument("--symbol", default="BTC/USDT", help="comma-separated symbols")
    ap.add_argument("--timeframe", default="1h", help="candle interval (1m/5m/15m/1h/4h/1d)")
    ap.add_argument("--months", type=int, default=12, help="number of months to fetch")
    ap.add_argument("--data-dir", default="data", help="CandleStore root")
    args = ap.parse_args(argv)

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    store = CandleStore(args.data_dir)
    total = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        for symbol in symbols:
            total += await _download_symbol(
                client, store, args.exchange, symbol, args.timeframe, args.months,
            )
    print(f"total rows written: {total}")
    return 0 if total > 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
