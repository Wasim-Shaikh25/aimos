"""Order-book snapshot aggregation (§4.2, card P1-T3).

Turns a raw L2 snapshot (ccxt ``fetch_order_book`` shape) into a
``BookAggregate``: best bid/ask, spread in bps, USD depth within ``book_depth_pct``
of mid on each side, and imbalance ∈ [−1, 1]. A rolling in-memory window keeps
the last N snapshots (default 1h at 10s) for the order-book engine (§5.6) and
persists 1-minute aggregates.

Pure functions here; polling cadence and network live in the runtime, and all
REST goes through the budgeter (§23.2).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Iterable, Sequence

from aimos.core.schemas import BookAggregate

# a price level is (price, size_base)
Level = Sequence[float]


def _depth_usd(levels: Iterable[Level], mid: float, within_frac: float, side: str) -> float:
    """Sum notional (price×size) for levels within ``within_frac`` of mid."""
    total = 0.0
    for price, size in levels:
        if side == "bid":
            if price >= mid * (1.0 - within_frac):
                total += price * size
        else:  # ask
            if price <= mid * (1.0 + within_frac):
                total += price * size
    return total


def aggregate_book(
    timestamp: datetime,
    bids: Sequence[Level],
    asks: Sequence[Level],
    book_depth_pct: float,
) -> BookAggregate:
    """Compute a ``BookAggregate`` from raw bid/ask ladders.

    ``bids`` descending by price, ``asks`` ascending (ccxt convention). Raises
    ``ValueError`` on an empty side (a crossed/one-sided book is a data error).
    """
    if not bids or not asks:
        raise ValueError("order book must have both bids and asks")
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000.0

    within = book_depth_pct / 100.0
    bid_depth = _depth_usd(bids, mid, within, "bid")
    ask_depth = _depth_usd(asks, mid, within, "ask")
    denom = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / denom if denom > 0 else 0.0
    # clamp against float error so the schema bound [-1, 1] always holds
    imbalance = max(-1.0, min(1.0, imbalance))

    return BookAggregate(
        timestamp=timestamp,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth,
        ask_depth_usd=ask_depth,
        imbalance=imbalance,
    )


def simulate_market_order(
    levels: Sequence[Level], size_usd: float, mid: float
) -> float:
    """Walk the book to fill ``size_usd`` and return realized slippage in bps (§5.5).

    ``levels`` are the levels on the side being HIT (asks for a buy, bids for a
    sell), best price first. Slippage = (vwap − mid)/mid × 10_000 in magnitude.
    If the book can't absorb the full size, slippage is computed on what filled
    plus a penalty for the unfilled remainder at the worst level price.
    """
    if size_usd <= 0 or mid <= 0 or not levels:
        return 0.0
    remaining = size_usd
    cost = 0.0
    filled = 0.0
    worst_price = float(levels[0][0])
    for price, size in levels:
        price = float(price); size = float(size)
        level_usd = price * size
        take = min(remaining, level_usd)
        cost += take  # notional spent
        filled += take / price  # base filled
        remaining -= take
        worst_price = price
        if remaining <= 0:
            break
    if remaining > 0:  # book exhausted — fill the rest at the worst price
        filled += remaining / worst_price
        cost += remaining
    vwap = cost / filled if filled > 0 else mid
    return abs(vwap - mid) / mid * 10_000.0


def detect_walls(
    levels: Sequence[Level],
    mid: float,
    within_pct: float,
    size_mult: float,
    age_seconds: dict[float, float] | None = None,
    spoof_age_seconds: float = 60.0,
) -> list[dict]:
    """Find resting walls: a level > ``size_mult`` × median size within ``within_pct``
    of mid (§5.6 rule 2). Flags ``spoof_suspect`` if the wall appeared recently.

    ``age_seconds`` maps price → seconds the level has existed (optional).
    Returns dicts with price, size, side_from_mid, spoof_suspect.
    """
    if not levels:
        return []
    within = within_pct / 100.0
    near = [(float(p), float(s)) for p, s in levels if abs(float(p) - mid) <= mid * within]
    if not near:
        return []
    sizes = sorted(s for _, s in near)
    median = sizes[len(sizes) // 2]
    if median <= 0:
        return []
    walls: list[dict] = []
    for price, size in near:
        if size > size_mult * median:
            age = (age_seconds or {}).get(price)
            spoof = age is not None and age < spoof_age_seconds
            walls.append({
                "price": price,
                "size": size,
                "above_mid": price > mid,
                "spoof_suspect": bool(spoof),
            })
    return walls


class BookWindow:
    """Rolling window of recent ``BookAggregate`` snapshots (§4.2)."""

    def __init__(self, maxlen: int = 360) -> None:
        self._buf: deque[BookAggregate] = deque(maxlen=maxlen)

    def add(self, agg: BookAggregate) -> None:
        self._buf.append(agg)

    def snapshots(self) -> list[BookAggregate]:
        return list(self._buf)

    def last(self, n: int) -> list[BookAggregate]:
        return list(self._buf)[-n:]

    def mean_imbalance(self, n: int = 30) -> float:
        recent = self.last(n)
        if not recent:
            return 0.0
        return sum(a.imbalance for a in recent) / len(recent)

    def __len__(self) -> int:
        return len(self._buf)


__all__ = ["BookWindow", "aggregate_book", "detect_walls", "simulate_market_order"]
