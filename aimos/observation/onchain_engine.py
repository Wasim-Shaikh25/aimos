"""On-chain engine (§5.9, card P2-T5). Phase-1 stub — registered but inert.

Returns ``[]`` always. Phase 3 activates active-address z-score and stablecoin
exchange inflow behind the identical engine interface, so turning it on is a
config flag — no structural change (§5.9).
"""

from __future__ import annotations

from aimos.core.schemas import Evidence, MarketContext
from aimos.observation.base import ObservationEngine


class OnchainEngine(ObservationEngine):
    name = "onchain_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        return []  # inert until Phase 3 (§5.9)


__all__ = ["OnchainEngine"]
