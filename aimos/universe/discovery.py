"""Market discovery (§16.1 A, card P15-T1).

``discover()`` turns a ccxt ``load_markets()`` mapping into typed ``MarketInfo``
records. Fetching is the caller's job (network) — this module is pure so tests
run on recorded market maps. Quality metrics used by the filters (24h volume,
book depth, spread, listing age, ATR%) arrive separately as ``MarketQuality``
because they come from tickers/candles, not ``load_markets``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class MarketInfo(BaseModel):
    """One tradable market on one venue (§16.1 A)."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    symbol: str  # unified ccxt symbol, e.g. "SOL/USDT"
    base: str
    quote: str
    type: str  # "spot" | "swap"
    active: bool
    min_notional: float
    lot_step: float
    taker_bps: float
    maker_bps: float


class MarketQuality(BaseModel):
    """Per-market quality metrics used by the filters (§16.1 B)."""

    model_config = ConfigDict(extra="forbid")

    volume_24h_usd: float
    book_depth_usd_0p5pct: float
    spread_bps: float
    listing_age_days: float
    atr_pct_per_day: Optional[float] = None  # §21.1 VolatilityFilter input


def _coerce_bps(value: Any, default: float) -> float:
    """ccxt fee is a fraction (0.001 = 10bps); convert to bps, tolerate None."""
    if value is None:
        return default
    return float(value) * 10_000.0


def discover(exchange_id: str, markets: dict[str, dict]) -> list[MarketInfo]:
    """Map a ccxt ``load_markets()`` result into ``MarketInfo`` records.

    ``markets`` is ``{symbol: market_dict}`` as ccxt returns it. Missing optional
    fields fall back to safe defaults (min_notional 5.0, fees to spec defaults).
    """
    out: list[MarketInfo] = []
    for m in markets.values():
        limits = m.get("limits") or {}
        cost = (limits.get("cost") or {})
        precision = m.get("precision") or {}
        out.append(
            MarketInfo(
                exchange=exchange_id,
                symbol=m["symbol"],
                base=m["base"],
                quote=m["quote"],
                type=m.get("type", "spot"),
                active=bool(m.get("active", True)),
                min_notional=float(cost.get("min") or 5.0),
                lot_step=float(precision.get("amount") or 0.0),
                taker_bps=_coerce_bps(m.get("taker"), 7.5),
                maker_bps=_coerce_bps(m.get("maker"), 2.0),
            )
        )
    return out


__all__ = ["MarketInfo", "MarketQuality", "discover"]
