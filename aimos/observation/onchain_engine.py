"""On-chain engine (§5.9, cards P2-T5 / functional upgrade).

Emits real evidence when an ``OnchainProvider`` supplies data: active-address
z-score (rising = bullish) and stablecoin exchange inflow (rising = bullish —
dry powder arriving). With no provider it returns [] (graceful, like every
book/feed-dependent engine when its feed is absent). Thresholds from config;
magic-number lint governs this module.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from aimos.core.clock import Clock
from aimos.core.indicators import zscore_last
from aimos.core.normalize import HALF
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import EngineConfig, ObservationEngine


class OnchainEngine(ObservationEngine):
    name = "onchain_engine"

    def __init__(
        self, cfg: EngineConfig, clock: Clock, reliability: float = HALF, provider: Optional[Any] = None
    ) -> None:
        super().__init__(cfg, clock, reliability)
        self.provider = provider  # aimos.data.onchain.OnchainProvider

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        if self.provider is None:
            return []  # no on-chain feed configured → nothing to observe
        data = self.provider.get(ctx.symbol)
        if not data:
            return []
        oc = self.cfg["onchain"]
        out: list[Evidence] = []

        aa = data.get("active_addresses") or []
        if len(aa) > int(oc["active_addr_window"]):
            z = zscore_last(aa[-int(oc["active_addr_window"]):])
            if z != 0:
                out.append(self._ev(ctx, "active_addresses", z,
                                    Direction.BULLISH if z > 0 else Direction.BEARISH))

        inflow = data.get("stablecoin_inflow") or []
        if len(inflow) > int(oc["stablecoin_inflow_window"]):
            z = zscore_last(inflow[-int(oc["stablecoin_inflow_window"]):])
            if z != 0:
                # rising stablecoin inflow to exchanges = dry powder → bullish
                out.append(self._ev(ctx, "stablecoin_inflow", z,
                                    Direction.BULLISH if z > 0 else Direction.BEARISH))
        return out

    def _ev(self, ctx: MarketContext, name: str, z: float, direction: Direction) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.D1,
            timestamp=ctx.now, name=name, value=float(z), direction=direction,
            strength=self._z_strength(z), reliability=self.reliability, meta={},
        )


__all__ = ["OnchainEngine"]
