"""Funding rate + open-interest series (§4.3, card P1-T3).

Thin normalizers that turn ccxt funding/OI shapes into a tidy time-indexed
DataFrame (ts, rate, oi) — the shape ``MarketContext.funding`` expects (§25.1).
Polling cadence lives in the runtime; all REST goes through the budgeter.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd


def build_funding_frame(
    rate_points: Sequence[tuple[int, float]],
    oi_points: Sequence[tuple[int, float]] | None = None,
) -> pd.DataFrame:
    """Merge funding-rate and open-interest point series into (ts, rate, oi).

    Each point is ``(timestamp_ms, value)``. Missing OI → NaN column. Deduped by
    timestamp and sorted ascending.
    """
    rate = pd.DataFrame(list(rate_points), columns=["ts_ms", "rate"])
    rate.index = pd.to_datetime(rate["ts_ms"], unit="ms", utc=True)
    rate = rate.drop(columns=["ts_ms"])[["rate"]]

    if oi_points:
        oi = pd.DataFrame(list(oi_points), columns=["ts_ms", "oi"])
        oi.index = pd.to_datetime(oi["ts_ms"], unit="ms", utc=True)
        oi = oi.drop(columns=["ts_ms"])[["oi"]]
        out = rate.join(oi, how="outer")
    else:
        out = rate.copy()
        out["oi"] = pd.NA

    out.index.name = "timestamp"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


__all__ = ["build_funding_frame"]
