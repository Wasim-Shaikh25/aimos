"""Whale engine (§5.8, card P2-T5). Consumes ctx.trades_large (large prints).

SPEC-GAP (§5.8): the plan z-scores net large-print flow vs its own 1h history,
but ``MarketContext`` (§25.1) carries only the current window of prints, not a
stored flow series. We normalize net flow by the window's gross flow (net/gross ∈
[−1, 1]) for strength; direction is the net-flow sign. Exchange netflow APIs
(deposits/withdrawals) remain the Phase-3 ``WhaleSource`` extension.
"""

from __future__ import annotations

from datetime import timedelta

from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


class WhaleEngine(ObservationEngine):
    name = "whale_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        prints = ctx.trades_large
        if not prints:
            return []
        # net + gross over the whole provided window (already trimmed to <= now)
        net = 0.0
        gross = 0.0
        for p in prints:
            signed = p.notional_usd if p.side == Direction.BULLISH else -p.notional_usd
            net += signed
            gross += p.notional_usd
        if gross <= 0 or net == 0:
            return []
        strength = self._clamp01(abs(net) / gross)
        name = "large_buys" if net > 0 else "large_sells"
        direction = Direction.BULLISH if net > 0 else Direction.BEARISH
        return [
            Evidence(
                source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.H1,
                timestamp=ctx.now, name=name, value=float(net), direction=direction,
                strength=strength, reliability=self.reliability,
                meta={"net_usd": float(net), "gross_usd": float(gross), "prints": len(prints)},
            )
        ]


__all__ = ["WhaleEngine"]
