"""Canonical asset registry — single source of truth (§16.1 B-C, §25.8, card P15-T2).

Canonical asset key = BASE only. ``SOL/USDT`` and ``SOL/USDC`` are the same asset
``SOL``; the registry stores the per-venue quote variants. All internal keys are
canonical bases (§25.8); venue symbols appear only in connectors and the broker.

Also holds:
* quote-suspension state (set by the depeg guard, §16.1 B-3), and
* delist handling (§16.1 C): dropping a (base, venue) flags whether cross-venue
  positions on that base must be flattened.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aimos.universe.discovery import MarketInfo


@dataclass
class TradableInfo:
    """What/where a base trades on one venue (§16.1 C matrix cell)."""

    market: MarketInfo
    active: bool = True


class Registry:
    """base → {venue: TradableInfo}. The manager other modules query."""

    def __init__(self, primary_exchange: str = "binance") -> None:
        self.primary_exchange = primary_exchange
        self._by_base: dict[str, dict[str, TradableInfo]] = {}
        self._suspended_quotes: set[str] = set()

    # -- population ----------------------------------------------------------

    def add_market(self, market: MarketInfo) -> None:
        base = market.base.upper()
        self._by_base.setdefault(base, {})[market.exchange] = TradableInfo(market=market)

    def add_all(self, markets: list[MarketInfo]) -> None:
        for m in markets:
            self.add_market(m)

    # -- queries -------------------------------------------------------------

    def bases(self) -> set[str]:
        return set(self._by_base.keys())

    def venues(self, base: str) -> list[str]:
        """Venues where ``base`` is active and its quote is not suspended."""
        base = base.upper()
        return [
            venue
            for venue, ti in self._by_base.get(base, {}).items()
            if ti.active and ti.market.quote.upper() not in self._suspended_quotes
        ]

    def market(self, base: str, venue: str) -> MarketInfo | None:
        ti = self._by_base.get(base.upper(), {}).get(venue)
        return ti.market if ti and ti.active else None

    def primary_market(self, base: str) -> MarketInfo | None:
        """The primary-venue market for per-asset Layer-1/2 analysis (§16.1 B-2)."""
        return self.market(base, self.primary_exchange)

    # -- quote suspension (depeg, §16.1 B-3) --------------------------------

    def suspend_quote(self, quote: str) -> None:
        self._suspended_quotes.add(quote.upper())

    def resume_quote(self, quote: str) -> None:
        self._suspended_quotes.discard(quote.upper())

    def is_quote_suspended(self, quote: str) -> bool:
        return quote.upper() in self._suspended_quotes

    # -- delist handling (§16.1 C) ------------------------------------------

    def delist(self, base: str, venue: str) -> dict:
        """Mark a (base, venue) delisted. Returns a flag payload.

        ``cross_venue_flatten`` is True when the base still trades on ≥1 OTHER
        venue — cross-venue positions on it must be flattened immediately
        (§16.1 C); single-venue positions elsewhere are unaffected.
        """
        base = base.upper()
        venue_map = self._by_base.get(base, {})
        if venue in venue_map:
            venue_map[venue].active = False
        remaining = [v for v, ti in venue_map.items() if ti.active]
        return {
            "base": base,
            "delisted_venue": venue,
            "remaining_venues": remaining,
            "cross_venue_flatten": len(remaining) >= 1,
        }


__all__ = ["Registry", "TradableInfo"]
