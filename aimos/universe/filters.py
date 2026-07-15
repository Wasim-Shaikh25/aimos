"""Stablecoin-quote + quality filters (§16.1 B, card P15-T1).

Enforces the system-wide invariant: **stablecoin-quoted pairs only**. Rejects
non-allowed quotes, stable/stable and fiat pairs, leveraged tokens, and markets
that fail liquidity/spread/age/volatility thresholds. The VolatilityFilter is
adapted from Freqtrade's pairlist concept (§21.1) — GPL-clean, see
``vendor/GPL_TRIPWIRE.md``.

Each rejection carries a machine-readable reason so the universe screen can show
"312 assets rejected: 190 volume, 61 spread, 40 leveraged-token, 21 age" (§16.2).
Thresholds come from ``config/universe.yaml`` — passed in, never hardcoded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from aimos.universe.discovery import MarketInfo, MarketQuality

# Leveraged-token name patterns (§16.1 B). Matched against the base symbol.
_LEVERAGED_RE = re.compile(r"(\d+[LS]$)|(UP$)|(DOWN$)|(BULL$)|(BEAR$)")


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str  # "" when passed; else one of the rejection codes


REASONS = {
    "quote",  # quote not in allowlist
    "stable_base",  # stable/stable or fiat base
    "leveraged",  # leveraged token
    "inactive",  # market not active
    "volume",
    "depth",
    "spread",
    "age",
    "volatility",
}


def is_leveraged_token(base: str) -> bool:
    return bool(_LEVERAGED_RE.search(base.upper()))


def filter_market(
    market: MarketInfo,
    quality: Optional[MarketQuality],
    *,
    allowed_quotes: set[str],
    exclude_bases: set[str],
    exclude_leveraged_tokens: bool,
    min_24h_volume_usd: float,
    min_book_depth_usd_0p5pct: float,
    max_spread_bps: float,
    min_listing_age_days: float,
    max_atr_pct_per_day: Optional[float] = None,
) -> FilterResult:
    """Apply all §16.1 B filters to one market. First failure wins.

    Structural filters (quote/base/leveraged/active) run before quality filters
    so a market can be rejected even without quality metrics. If quality is None,
    quality-based filters are skipped (the market survives structural checks).
    """
    quote = market.quote.upper()
    base = market.base.upper()

    if quote not in allowed_quotes:
        return FilterResult(False, "quote")  # no BTC/EUR, no ETH/BTC
    if base in exclude_bases:
        return FilterResult(False, "stable_base")  # no stable/stable, no fiat
    if exclude_leveraged_tokens and is_leveraged_token(base):
        return FilterResult(False, "leveraged")
    if not market.active:
        return FilterResult(False, "inactive")

    if quality is None:
        return FilterResult(True, "")

    if quality.volume_24h_usd < min_24h_volume_usd:
        return FilterResult(False, "volume")
    if quality.book_depth_usd_0p5pct < min_book_depth_usd_0p5pct:
        return FilterResult(False, "depth")
    if quality.spread_bps > max_spread_bps:
        return FilterResult(False, "spread")
    if quality.listing_age_days < min_listing_age_days:
        return FilterResult(False, "age")
    if (
        max_atr_pct_per_day is not None
        and quality.atr_pct_per_day is not None
        and quality.atr_pct_per_day > max_atr_pct_per_day
    ):
        return FilterResult(False, "volatility")

    return FilterResult(True, "")


__all__ = ["FilterResult", "REASONS", "filter_market", "is_leveraged_token"]
