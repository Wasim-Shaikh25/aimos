"""Candle fetching, gap-filling, resampling, and parquet storage (§4.1, card P1-T2).

Fetching goes through a ``CandleFetcher`` protocol (ccxt implements it in
``connectors/``) so tests inject a recorded fetcher and touch no network.

Gap-fill policy (§4.1 rule 3): a missing candle is forward-filled — close
carried into O/H/L/C, ``volume=0`` and ``synthetic=True``. Layer-1 volume math
must skip synthetic candles. Storage is append-only parquet, deduped by
timestamp. Lower timeframes resample locally into higher ones to cut API calls.

All timestamps are UTC-aware (§0 rule 6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, Sequence

import pandas as pd
import structlog

log = structlog.get_logger(__name__)

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Timeframe -> (pandas resample rule, timedelta). Uses non-deprecated aliases.
_TF_RULE: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
_TF_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


class CandleFetcher(Protocol):
    """Minimal OHLCV source (ccxt ``fetch_ohlcv`` shape)."""

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None, limit: int
    ) -> list[list[float]]:
        """Return rows [ts_ms, open, high, low, close, volume] ascending by ts."""
        ...


def timeframe_delta(timeframe: str) -> timedelta:
    try:
        return _TF_DELTA[timeframe]
    except KeyError as exc:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown timeframe {timeframe!r}") from exc


def _rows_to_df(rows: Sequence[Sequence[float]]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows), columns=["ts_ms", *OHLCV_COLUMNS])
    df.index = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df.index.name = "timestamp"
    df = df.drop(columns=["ts_ms"])
    return df[OHLCV_COLUMNS].astype(float)


def fetch_candles(
    fetcher: CandleFetcher,
    symbol: str,
    timeframe: str,
    depth: int,
    until: datetime | None = None,
    page_limit: int = 1000,
) -> pd.DataFrame:
    """Fetch ~``depth`` candles ending at ``until`` via forward paging.

    Pages forward from ``until − depth×delta``, advancing the cursor past each
    page's last timestamp until ``until`` is reached or the fetcher is exhausted.
    Returns the last ``depth`` candles gap-filled, deduped, UTC-indexed with a
    ``synthetic`` column. Network-free when ``fetcher`` is a recorded source.
    """
    delta = timeframe_delta(timeframe)
    end = until or datetime.now(timezone.utc)
    start = end - delta * depth
    frames: list[pd.DataFrame] = []

    since = start
    guard = 0
    max_pages = depth // max(page_limit, 1) + 4
    while since < end and guard < max_pages:
        guard += 1
        since_ms = int(since.timestamp() * 1000)
        rows = fetcher.fetch_ohlcv(symbol, timeframe, since_ms, page_limit)
        if not rows:
            break
        df = _rows_to_df(rows)
        df = df[(df.index >= start) & (df.index <= end)]
        if df.empty:
            break
        frames.append(df)
        last = df.index.max()
        next_since = last + delta
        if next_since <= since:  # no forward progress
            break
        since = next_since
        if len(rows) < page_limit:  # fetcher exhausted
            break

    if not frames:
        return _empty_frame()
    combined = pd.concat(frames)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined = combined.tail(depth)
    return gap_fill(combined, timeframe)


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame(columns=[*OHLCV_COLUMNS, "synthetic"])
    df.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return df


def gap_fill(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Reindex to a complete grid, forward-fill gaps, flag them ``synthetic``.

    Real bars → ``synthetic=False``; forward-filled bars → close carried into
    O/H/L/C, ``volume=0``, ``synthetic=True`` (§4.1 rule 3).
    """
    if df.empty:
        out = df.copy()
        if "synthetic" not in out.columns:
            out["synthetic"] = pd.Series(dtype=bool)
        return out

    rule = _TF_RULE[timeframe]
    full = pd.date_range(df.index.min(), df.index.max(), freq=rule, tz="UTC")
    out = df.reindex(full)
    out.index.name = "timestamp"

    missing = out["close"].isna()
    # carry last known close forward as the synthetic price
    out["close"] = out["close"].ffill()
    for col in ("open", "high", "low"):
        out[col] = out[col].where(~missing, out["close"])
    out["volume"] = out["volume"].where(~missing, 0.0)
    out["synthetic"] = missing.values
    # any leading NaNs (no prior close to carry) are dropped
    out = out.dropna(subset=["close"])
    return out[[*OHLCV_COLUMNS, "synthetic"]]


def resample(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample 1m candles to a higher timeframe (§4.1 rule 5)."""
    rule = _TF_RULE[timeframe]
    agg = df_1m.resample(rule).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return agg.dropna(subset=["open"])


class CandleStore:
    """Append-only parquet store, deduped by timestamp (§4.1 rule 4)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path_for(self, exchange: str, symbol: str, timeframe: str) -> Path:
        safe = symbol.replace("/", "_")
        return self.root / exchange / safe / f"{timeframe}.parquet"

    def write(self, exchange: str, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        """Merge ``df`` into any existing file, dedup by timestamp, persist."""
        path = self.path_for(exchange, symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, df])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        else:
            merged = df.sort_index()
        merged.to_parquet(path)
        return path

    def read(self, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame:
        path = self.path_for(exchange, symbol, timeframe)
        if not path.exists():
            return _empty_frame()
        return pd.read_parquet(path)


def has_gaps(df: pd.DataFrame, timeframe: str) -> bool:
    """True if the (non-synthetic) grid has any missing timestamps."""
    if df.empty:
        return False
    expected = pd.date_range(df.index.min(), df.index.max(), freq=_TF_RULE[timeframe], tz="UTC")
    return len(expected) != len(df.index)


def _cli(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    """`python -m aimos.data.candles --symbol BTC/USDT --tf 1h --depth 2000`."""
    import argparse

    from aimos.data.connectors.ccxt_connector import CcxtCandleFetcher

    parser = argparse.ArgumentParser(description="Fetch gapless candles to parquet.")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tf", required=True)
    parser.add_argument("--depth", type=int, default=2000)
    parser.add_argument("--root", default="data")
    args = parser.parse_args(argv)

    fetcher = CcxtCandleFetcher(args.exchange)
    df = fetch_candles(fetcher, args.symbol, args.tf, args.depth)
    store = CandleStore(args.root)
    path = store.write(args.exchange, args.symbol, args.tf, df)
    print(f"wrote {len(df)} candles ({int(df['synthetic'].sum())} synthetic) → {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())


__all__ = [
    "CandleFetcher",
    "CandleStore",
    "OHLCV_COLUMNS",
    "fetch_candles",
    "gap_fill",
    "has_gaps",
    "resample",
    "timeframe_delta",
]
