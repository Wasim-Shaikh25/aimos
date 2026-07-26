"""Convert venue-agnostic StreamEvents into MarketContext inputs (§5.0, §5.8).

Live websocket events are turned into ``BookAggregate`` and ``LargePrint``
objects that the observation engines can consume.  This module lives in
``data`` (below ``observation``) so the layer contract is preserved.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aimos.core.schemas import BookAggregate, Direction, LargePrint
from aimos.data.live_source import base_of
from aimos.data.streaming import StreamEvent


def _mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def _depth_near_mid(levels: list[list[float]], mid: float, frac: float) -> float:
    """Return USD depth within ``frac`` of ``mid`` for a bid/ask side."""
    if not levels or mid <= 0:
        return 0.0
    total = 0.0
    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        if abs(price - mid) / mid <= frac:
            total += price * qty
    return total


def book_from_depth(event: StreamEvent, depth_frac: float = 0.005) -> BookAggregate:
    """Build a BookAggregate from a @depth StreamEvent."""
    bids = [list(p) for p in event.data.get("bids", [])]
    asks = [list(p) for p in event.data.get("asks", [])]
    best_bid = max((p for p, _ in bids), default=0.0)
    best_ask = min((p for p, _ in asks), default=0.0)
    mid = _mid(best_bid, best_ask) if best_bid > 0 and best_ask > 0 else 0.0
    spread_bps = 0.0
    if mid > 0 and best_bid > 0 and best_ask > 0:
        spread_bps = (best_ask - best_bid) / mid * 10_000.0
    bid_depth = _depth_near_mid(bids, mid, depth_frac)
    ask_depth = _depth_near_mid(asks, mid, depth_frac)
    imbalance = 0.0
    if bid_depth + ask_depth > 0:
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    return BookAggregate(
        timestamp=event.timestamp,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth,
        ask_depth_usd=ask_depth,
        imbalance=imbalance,
    )


def large_print_from_trade(event: StreamEvent) -> LargePrint:
    """Build a LargePrint from a @trade StreamEvent."""
    price = float(event.data.get("price", 0.0))
    qty = float(event.data.get("qty", 0.0))
    buyer_is_maker = bool(event.data.get("buyer_is_maker", False))
    side = Direction.BEARISH if buyer_is_maker else Direction.BULLISH
    return LargePrint(
        timestamp=event.timestamp,
        symbol=event.symbol,
        side=side,
        notional_usd=price * qty,
        price=price,
    )


class StreamFeed:
    """Ingest StreamEvents and produce per-symbol book/trade slices for the pipeline.

    The feed keeps one latest book snapshot per symbol and a bounded deque of
    recent large prints.  ``get_book`` / ``get_trades`` return values that can be
    passed directly to ``build_context``.
    """

    def __init__(
        self,
        book_window_minutes: float = 1.0,
        trade_window_minutes: float = 5.0,
        min_notional_usd: float = 100.0,
        max_recent_trades: int = 1_000,
    ) -> None:
        self.book_window_minutes = book_window_minutes
        self.trade_window_minutes = trade_window_minutes
        self.min_notional_usd = min_notional_usd
        self._books: dict[str, BookAggregate] = {}
        self._trades: dict[str, deque[LargePrint]] = {}
        self._max_recent_trades = max_recent_trades

    def handle(self, event: StreamEvent) -> None:
        """Normalize and store a single stream event keyed by base symbol."""
        base = base_of(event.symbol)
        now = event.timestamp
        if event.type == "book":
            self._books[base] = book_from_depth(event)
        elif event.type == "trade":
            prints = self._trades.setdefault(base, deque(maxlen=self._max_recent_trades))
            lp = large_print_from_trade(event)
            if lp.notional_usd >= self.min_notional_usd:
                prints.append(lp)
            self._trim(prints, now, self.trade_window_minutes)

    def _trim(
        self, prints: deque[LargePrint], now: datetime, minutes: float
    ) -> None:
        cutoff = now - timedelta(minutes=minutes)
        while prints and prints[0].timestamp < cutoff:
            prints.popleft()

    def get_book(self, symbol: str, now: Optional[datetime] = None) -> list[BookAggregate]:
        """Return the latest book snapshot for ``symbol`` if it is fresh."""
        now = now or datetime.now(timezone.utc)
        book = self._books.get(symbol)
        if book is None:
            return []
        cutoff = now - timedelta(minutes=self.book_window_minutes)
        if book.timestamp < cutoff:
            return []
        return [book]

    def get_trades(self, symbol: str, now: Optional[datetime] = None) -> list[LargePrint]:
        """Return recent large prints for ``symbol``."""
        now = now or datetime.now(timezone.utc)
        prints = self._trades.get(symbol, deque())
        self._trim(prints, now, self.trade_window_minutes)
        return list(prints)

    def snapshot(self, symbol: str, now: Optional[datetime] = None) -> dict[str, Any]:
        """Return a dict suitable for expanding a MarketContext."""
        return {
            "orderbook_window": self.get_book(symbol, now),
            "trades_large": self.get_trades(symbol, now),
        }


__all__ = ["StreamFeed", "book_from_depth", "large_print_from_trade"]
