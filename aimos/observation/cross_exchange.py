"""Cross-Exchange engine (§5.11, card P2-T6). Consumes ctx.venue_snapshot.

price_dislocation converts every venue mid to USD via live stable rates BEFORE
computing dislocation (§16.1 B-3), so a stable/stable gap is not counted as
profit. lead_lag + venue_divergence_volume are computed from per-venue series/
rel-vols when a provider supplies them (the streaming layer, §5.11 rules 2-3).
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
from typing import Mapping, Optional

import numpy as np

from aimos.core.normalize import BPS, HALF
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe, VenueTop
from aimos.observation.base import ObservationEngine


def compute_dislocation(
    venue_tops: Mapping[str, VenueTop],
    venue_quotes: Optional[Mapping[str, str]] = None,
    stable_rates: Optional[Mapping[str, float]] = None,
    max_quote_age_seconds: Optional[float] = None,
    max_venue_skew_seconds: Optional[float] = None,
    now: Optional[datetime] = None,
) -> tuple[float, tuple[str, str]] | None:
    """Max executable pairwise spread in bps after converting to USD (§5.11).

    Unlike a mid-to-mid gap, an arb is only profitable when the rich venue's
    best_bid exceeds the cheap venue's best_ask: ``bid[rich] - ask[cheap]``.
    Stale quotes and venues whose observation times differ too much are dropped.

    ``venue_quotes[v]`` names each venue's quote stable; ``stable_rates[q]`` is
    that stable's USD rate (defaults to 1.0). Returns (bps, (cheap, rich)) or None.
    """
    if now is not None and (max_quote_age_seconds is not None or max_venue_skew_seconds is not None):
        fresh: dict[str, VenueTop] = {}
        for venue, top in venue_tops.items():
            if top.timestamp is not None:
                age = (now - top.timestamp).total_seconds()
                if age < 0:
                    age = 0
                if max_quote_age_seconds is not None and age > max_quote_age_seconds:
                    continue
            fresh[venue] = top
        venue_tops = fresh
        if max_venue_skew_seconds is not None and len(venue_tops) >= 2:
            timestamps = [top.timestamp for top in venue_tops.values() if top.timestamp is not None]
            if timestamps and (max(timestamps) - min(timestamps)).total_seconds() > max_venue_skew_seconds:
                return None
    if len(venue_tops) < 2:
        return None
    best_bps = 0.0
    best_pair = ("", "")
    for a, b in combinations(venue_tops, 2):
        top_a, top_b = venue_tops[a], venue_tops[b]
        quote_a = (venue_quotes or {}).get(a, "USDT")
        quote_b = (venue_quotes or {}).get(b, "USDT")
        rate_a = (stable_rates or {}).get(quote_a, 1.0)
        rate_b = (stable_rates or {}).get(quote_b, 1.0)
        ref = (top_a.mid * rate_a + top_b.mid * rate_b) / 2.0
        if ref <= 0:
            continue
        # a = cheap if we can buy at a's ask and sell at b's bid at a profit.
        executable_ab = top_b.best_bid * rate_b - top_a.best_ask * rate_a
        bps_ab = executable_ab / ref * BPS
        if bps_ab > best_bps:
            best_bps = bps_ab
            best_pair = (a, b)
        # b = cheap, a = rich.
        executable_ba = top_a.best_bid * rate_a - top_b.best_ask * rate_b
        bps_ba = executable_ba / ref * BPS
        if bps_ba > best_bps:
            best_bps = bps_ba
            best_pair = (b, a)
    return (best_bps, best_pair) if best_bps > 0 else None


def compute_lead_lag(
    venue_series: Mapping[str, list[float]], lag: int = 1
) -> tuple[str, Direction, float] | None:
    """Identify the leading venue via lagged cross-correlation (§5.11 rule 2).

    For each venue, correlate its lag-shifted returns against the pooled
    consensus; the highest lead-correlation venue is the leader. If that leader
    just moved, direction = its move. Returns (leader, direction, strength).
    """
    from aimos.core.indicators import correlation

    returns: dict[str, np.ndarray] = {}
    for v, series in venue_series.items():
        arr = np.asarray(series, dtype=float)
        if arr.size > lag + 2:
            returns[v] = np.diff(arr) / arr[:-1]
    if len(returns) < 2:
        return None
    consensus = np.mean([r[-min(len(x) for x in returns.values()):] for r in returns.values()], axis=0)
    best_v, best_corr = "", 0.0
    for v, r in returns.items():
        n = min(len(r), len(consensus))
        lead = correlation(r[-n:][:-lag] if lag else r[-n:], consensus[-n:][lag:] if lag else consensus[-n:])
        if abs(lead) > abs(best_corr):
            best_v, best_corr = v, lead
    if not best_v:
        return None
    last_move = returns[best_v][-1]
    if last_move == 0:
        return None
    direction = Direction.BULLISH if last_move > 0 else Direction.BEARISH
    return best_v, direction, min(abs(best_corr), 1.0)


def venue_divergence(rel_vols: Mapping[str, float], hi: float, lo: float) -> bool:
    """One venue's rel_vol > hi while all others < lo → manipulation flag (§5.11 rule 3)."""
    if len(rel_vols) < 2:
        return False
    vals = sorted(rel_vols.values(), reverse=True)
    return vals[0] > hi and all(v < lo for v in vals[1:])


class CrossExchangeEngine(ObservationEngine):
    name = "cross_exchange_engine"

    def __init__(self, cfg, clock, reliability=HALF, venue_series_provider=None, venue_relvol_provider=None):
        super().__init__(cfg, clock, reliability)
        self.venue_series_provider = venue_series_provider  # base → {venue: [prices]}
        self.venue_relvol_provider = venue_relvol_provider  # base → {venue: rel_vol}

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        cc = self.cfg["cross_exchange"]
        out = self._dislocation(ctx, cc)
        out.extend(self._lead_lag(ctx, cc))
        out.extend(self._venue_divergence(ctx, cc))
        return out

    def _dislocation(self, ctx: MarketContext, cc) -> list[Evidence]:
        snap = ctx.venue_snapshot
        if len(snap) < 2:
            return []
        quote = ctx.symbol.split("/")[1] if "/" in ctx.symbol else "USDT"
        venue_quotes = {v: quote for v in snap}
        result = compute_dislocation(
            snap,
            venue_quotes=venue_quotes,
            max_quote_age_seconds=cc.get("max_quote_age_seconds"),
            max_venue_skew_seconds=cc.get("max_venue_skew_seconds"),
            now=ctx.now,
        )
        if result is None:
            return []
        bps, (cheap, rich) = result
        floor = float(cc["fee_floor_bps"]) + float(cc["dislocation_extra_bps"])
        if bps <= floor:
            return []
        strength = self._clamp01((bps - floor) / floor)
        return [
            Evidence(
                source=f"{self.name}.price_dislocation", symbol=ctx.symbol,
                timeframe=Timeframe.M5, timestamp=ctx.now, name="price_dislocation",
                value=float(bps), direction=Direction.NEUTRAL, strength=strength,
                reliability=self.reliability,
                meta={"bps": float(bps), "buy_venue": cheap, "sell_venue": rich},
            )
        ]

    def _lead_lag(self, ctx: MarketContext, cc) -> list[Evidence]:
        if self.venue_series_provider is None:
            return []
        series = self.venue_series_provider(ctx.symbol)
        if not series:
            return []
        result = compute_lead_lag(series)
        if result is None:
            return []
        leader, direction, strength = result
        return [Evidence(
            source=f"{self.name}.lead_lag", symbol=ctx.symbol, timeframe=Timeframe.M5,
            timestamp=ctx.now, name="lead_lag", value=strength, direction=direction,
            strength=self._clamp01(strength), reliability=self.reliability,
            meta={"leader": leader},
        )]

    def _venue_divergence(self, ctx: MarketContext, cc) -> list[Evidence]:
        if self.venue_relvol_provider is None:
            return []
        rel_vols = self.venue_relvol_provider(ctx.symbol)
        if not rel_vols:
            return []
        if venue_divergence(rel_vols, float(cc["venue_div_rel_vol_hi"]), float(cc["venue_div_others_lo"])):
            return [Evidence(
                source=f"{self.name}.venue_divergence_volume", symbol=ctx.symbol,
                timeframe=Timeframe.M5, timestamp=ctx.now, name="venue_divergence_volume",
                value=max(rel_vols.values()), direction=Direction.NEUTRAL, strength=1.0,
                reliability=self.reliability, meta={"manipulation_flag": True, "rel_vols": dict(rel_vols)},
            )]
        return []


__all__ = ["CrossExchangeEngine", "compute_dislocation", "compute_lead_lag", "venue_divergence"]
