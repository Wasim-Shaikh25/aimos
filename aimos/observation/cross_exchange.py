"""Cross-Exchange engine (§5.11, card P2-T6). Consumes ctx.venue_snapshot.

price_dislocation converts every venue mid to USD via live stable rates BEFORE
computing dislocation (§16.1 B-3), so a stable/stable gap is not counted as
profit. lead_lag and venue_divergence_volume are Phase-1 stubs (§5.11 rules 2-3).
"""

from __future__ import annotations

from itertools import combinations
from typing import Mapping, Optional

from aimos.core.normalize import BPS
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


def compute_dislocation(
    venue_mids: Mapping[str, float],
    venue_quotes: Optional[Mapping[str, str]] = None,
    stable_rates: Optional[Mapping[str, float]] = None,
) -> tuple[float, tuple[str, str]] | None:
    """Max pairwise mid deviation in bps after converting mids to USD (§5.11).

    ``venue_quotes[v]`` names each venue's quote stable; ``stable_rates[q]`` is
    that stable's USD rate (defaults to 1.0). Returns (bps, (cheap, rich)) or None.
    """
    if len(venue_mids) < 2:
        return None
    usd: dict[str, float] = {}
    for venue, mid in venue_mids.items():
        quote = (venue_quotes or {}).get(venue, "USDT")
        rate = (stable_rates or {}).get(quote, 1.0)
        usd[venue] = mid * rate
    best_bps = 0.0
    best_pair = ("", "")
    for a, b in combinations(usd, 2):
        ref = (usd[a] + usd[b]) / 2.0
        if ref <= 0:
            continue
        dev_bps = abs(usd[a] - usd[b]) / ref * BPS
        if dev_bps > best_bps:
            best_bps = dev_bps
            best_pair = (a, b) if usd[a] < usd[b] else (b, a)
    return best_bps, best_pair


class CrossExchangeEngine(ObservationEngine):
    name = "cross_exchange_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        snap = ctx.venue_snapshot
        if len(snap) < 2:
            return []
        cc = self.cfg["cross_exchange"]
        mids = {v: top.mid for v, top in snap.items()}
        result = compute_dislocation(mids)
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


__all__ = ["CrossExchangeEngine", "compute_dislocation"]
