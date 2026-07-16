"""MarketContext builder (§25.1, §5.0 — card P2-T1).

Assembles the per-asset ``MarketContext`` that every observation engine consumes.
Windows are trimmed to end at ``now`` so no engine can see future data
(anti-lookahead, §9.1). Lives in ``data`` (below observation) so observation
depends on it, not vice versa.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional

import pandas as pd

from aimos.core.schemas import (
    BookAggregate,
    Headline,
    LargePrint,
    MarketContext,
    Timeframe,
    VenueTop,
)


def _trim(df: Optional[pd.DataFrame], now: datetime) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return df
    return df[df.index <= now]


def build_context(
    symbol: str,
    now: datetime,
    candles: Mapping[Timeframe, pd.DataFrame],
    orderbook_window: Optional[list[BookAggregate]] = None,
    funding: Optional[pd.DataFrame] = None,
    trades_large: Optional[list[LargePrint]] = None,
    headlines: Optional[list[Headline]] = None,
    peers: Optional[Mapping[str, pd.DataFrame]] = None,
    venue_snapshot: Optional[Mapping[str, VenueTop]] = None,
) -> MarketContext:
    """Build a MarketContext with every candle/funding/peer window ending at ``now``."""
    trimmed = {tf: _trim(df, now) for tf, df in candles.items() if df is not None}
    trimmed_peers = {k: _trim(df, now) for k, df in (peers or {}).items()}
    book = [b for b in (orderbook_window or []) if b.timestamp <= now]
    prints = [p for p in (trades_large or []) if p.timestamp <= now]
    heads = [h for h in (headlines or []) if h.timestamp <= now]

    return MarketContext(
        symbol=symbol,
        now=now,
        candles=trimmed,
        orderbook_window=book,
        funding=_trim(funding, now),
        trades_large=prints,
        headlines=heads,
        peers=trimmed_peers,
        venue_snapshot=dict(venue_snapshot or {}),
    )


__all__ = ["build_context"]
