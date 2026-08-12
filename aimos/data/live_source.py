"""Market-data sources for the paper loop (§4, card P5-T1 wiring).

Paper trading needs only PUBLIC market data — no API keys. ``CcxtPublicSource``
fetches public OHLCV via ccxt (lazy import, no auth). ``SyntheticSource``
generates a deterministic random walk so the whole pipeline runs fully offline
(no network) for a self-contained test run. Both return the gap-filled DataFrame
(OHLCV + ``synthetic``) the observation engines expect. Not in the linted layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

import numpy as np
import pandas as pd

from aimos.core.schemas import VenueTop
from aimos.data.candles import fetch_candles, gap_fill

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class DataSource(Protocol):
    def fetch(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame: ...


class CcxtPublicSource:
    """Public OHLCV via ccxt — NO API keys (public endpoints only).

    The ccxt client is built lazily on first ``fetch`` so constructing this
    source never fails when ccxt isn't installed (callers can fall back).
    """

    def __init__(self, exchange_id: str = "binance") -> None:
        self.exchange_id = exchange_id
        self._fetcher = None

    def _ensure(self) -> None:
        if self._fetcher is None:
            from aimos.data.connectors.ccxt_connector import CcxtCandleFetcher  # lazy
            self._fetcher = CcxtCandleFetcher(self.exchange_id)

    def fetch(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        self._ensure()
        return fetch_candles(self._fetcher, symbol, timeframe, depth=bars)


class SyntheticSource:
    """Deterministic random-walk candles for a fully-offline run (no network)."""

    def __init__(self, seed: int = 0, start_price: float = 30_000.0) -> None:
        self.seed = seed
        self.start_price = start_price

    def fetch(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        # per-symbol deterministic seed so BTC and ETH differ but replay-stable
        rng = np.random.default_rng(self.seed + (hash(symbol) % 10_000))
        rets = rng.normal(0, 0.01, bars)
        close = self.start_price * np.cumprod(1 + rets)
        opens = np.concatenate([[close[0]], close[:-1]])
        highs = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.003, bars)))
        lows = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.003, bars)))
        vols = np.abs(rng.normal(1000, 200, bars))
        step = timedelta(minutes=_TF_MINUTES.get(timeframe, 60))
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        idx = pd.DatetimeIndex([end - step * (bars - 1 - i) for i in range(bars)], tz="UTC")
        df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": close,
                           "volume": vols}, index=idx)
        return gap_fill(df, timeframe)


def base_of(symbol: str) -> str:
    return symbol.split("/")[0] if "/" in symbol else symbol


# -- cross-exchange top-of-book (§5.11) --------------------------------------


def synthetic_venue_snapshot(
    symbol: str, base_mid: float, now: datetime, venues: list[str],
    dislocation_bps: float = 30.0, spread_bps: float = 1.0,
) -> dict[str, VenueTop]:
    """Deterministic multi-venue top-of-book with a replay-stable dislocation.

    Venue 0 is the reference; each later venue is offset a fixed, per-venue
    number of bps so ``price_dislocation`` fires offline (no network). Lets the
    cross-exchange engine + P8 arb plugin run fully self-contained.
    """
    snap: dict[str, VenueTop] = {}
    n = max(len(venues) - 1, 1)
    for i, venue in enumerate(venues):
        # spread venues symmetrically around base_mid so the max pairwise
        # gap (cheapest vs richest) equals dislocation_bps
        off = ((i / n) - 0.5) * dislocation_bps if len(venues) > 1 else 0.0
        mid = base_mid * (1.0 + off / 10_000.0)
        half = mid * (spread_bps / 2.0) / 10_000.0
        snap[venue] = VenueTop(
            exchange=venue, best_bid=mid - half, best_ask=mid + half,
            mid=mid, timestamp=now,
        )
    return snap


def live_venue_snapshot(
    symbol: str, now: datetime, venues: list[str],
    fetchers: Mapping[str, object] | None = None,
) -> dict[str, VenueTop]:
    """Public best bid/ask per venue via ccxt (no keys). Skips venues that fail.

    ``fetchers`` (venue → object with ``fetch_top_of_book``) is injectable for
    tests; otherwise a ccxt fetcher is built lazily per venue. Each successful
    fetch is stamped with its own observation time so staleness checks can run.
    """
    from aimos.data.connectors.ccxt_connector import CcxtCandleFetcher  # lazy

    snap: dict[str, VenueTop] = {}
    for venue in venues:
        try:
            f = (fetchers or {}).get(venue) or CcxtCandleFetcher(venue)
            bid, ask = f.fetch_top_of_book(symbol)
            snap[venue] = VenueTop(
                exchange=venue, best_bid=bid, best_ask=ask,
                mid=(bid + ask) / 2.0, timestamp=datetime.now(timezone.utc),
            )
        except Exception:  # noqa: BLE001 — a dead venue just drops out of the snapshot
            continue
    return snap


def perturb_for_venue(
    df: pd.DataFrame, venue: str, salt: str = "",
    base_offset_bps: float = 32.0, noise_bps: float = 5.0,
) -> pd.DataFrame:
    """Derive a venue's candles from a shared base walk (offline realism).

    Same asset trades within a few/low-tens of bps across venues, so instead of
    independent random walks we take one canonical series and apply a small,
    deterministic per-(venue, coin) offset + tiny per-bar noise (bps-scale). The
    ``salt`` (the coin) makes each coin's cross-venue dislocation differ — some
    tight, some wide enough to arb — instead of every coin showing the same gap.
    Live data needs none of this (real per-venue prices are already close).
    """
    key = abs(hash(f"{venue}|{salt}"))
    rng = np.random.default_rng(key % 9_999)
    offset = (((key % 1000) / 1000.0) - 0.5) * 2.0 * base_offset_bps
    noise = rng.normal(0.0, noise_bps, len(df))
    factor = 1.0 + (offset + noise) / 10_000.0
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].to_numpy() * factor
    return out


def venue_snapshot_for(
    features: Mapping, paper: Mapping, registry, symbol: str, mid: float,
    now: datetime, live_data: bool,
):
    """Cross-exchange top-of-book for one coin, using ITS actual venues (§5.11).

    When a ``Registry`` is available we look up the venues this specific base
    trades on (``registry.venues(base)`` — respects delist/quote-suspension) so a
    coin on binance/kraken/coinbase is checked on all three, and a single-venue
    coin is skipped (no cross-venue arb possible). Without a registry (dev mode)
    we fall back to the configured ``cross_venues``. Returns None when disabled or
    fewer than 2 venues are available.
    """
    if not features.get("cross_exchange_enabled"):
        return None
    base = base_of(symbol)
    if registry is not None and registry.bases():
        venues = registry.venues(base)
        if len(venues) < 2:
            return None  # coin trades on < 2 venues → nothing to arbitrage
    else:
        venues = list(paper.get("cross_venues", []))
        if len(venues) < 2:
            return None
    if live_data:
        return live_venue_snapshot(symbol, now, venues)
    return synthetic_venue_snapshot(symbol, mid, now, venues)


__all__ = [
    "CcxtPublicSource", "DataSource", "SyntheticSource", "base_of",
    "live_venue_snapshot", "perturb_for_venue", "synthetic_venue_snapshot",
    "venue_snapshot_for",
]
