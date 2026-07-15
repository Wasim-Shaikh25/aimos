"""Liquidity engine (§5.5, card P2-T4).

Consumes the order-book aggregate window (§4.2). Emits spread (z-scored, risk),
thin_book (depth percentile), and a slippage_estimate carrier whose meta feeds
the §7 cost model.

SPEC-GAP (§5.5 rules 3-4): liquidity zones and the exact market-order slippage
simulation need raw L2 levels, which ``MarketContext.orderbook_window`` (§25.1)
does not carry — those arrive with the streaming feed (card P2-T7). With only
aggregates this engine emits spread/thin_book and a depth-based slippage proxy;
``data.orderbook.simulate_market_order`` does the exact sim where levels exist.
"""

from __future__ import annotations

import numpy as np

from aimos.core.schemas import Direction, Evidence, MarketContext
from aimos.observation.base import ObservationEngine


class LiquidityEngine(ObservationEngine):
    name = "liquidity_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        window = ctx.orderbook_window
        lc = self.cfg["liquidity"]
        if len(window) < 2:
            return []
        ts = window[-1].timestamp
        out: list[Evidence] = []

        spreads = np.array([b.spread_bps for b in window], dtype=float)
        depths = np.array([b.bid_depth_usd + b.ask_depth_usd for b in window], dtype=float)

        # rule 1: spread z-score (NEUTRAL, raises risk when wide)
        std = float(spreads.std())
        if std > 0:
            z = float((spreads[-1] - spreads.mean()) / std)
            meta = {"spread_bps": float(spreads[-1])}
            if abs(z) >= float(lc["spread_z_risk"]):
                meta["risk_gate"] = True
            out.append(self._ev(ctx, ts, "spread", z, self._z_strength(z), meta))

        # rule 2: thin book — current depth below Nth percentile of the window
        pct = float(lc["thin_book_percentile"])
        threshold = float(np.percentile(depths, pct))
        if depths[-1] < threshold:
            span = threshold if threshold > 0 else 1.0
            strength = self._clamp01((threshold - depths[-1]) / span)
            out.append(self._ev(ctx, ts, "thin_book", depths[-1], strength,
                                 {"depth_usd": float(depths[-1]), "risk_gate": True}))

        # rule 4: slippage estimate carrier (meta feeds §7 cost model)
        out.append(self._ev(ctx, ts, "slippage_estimate", depths[-1], 0.0,
                             {"bid_depth_usd": float(window[-1].bid_depth_usd),
                              "ask_depth_usd": float(window[-1].ask_depth_usd)}))
        return out

    def _ev(self, ctx, ts, name, value, strength, meta) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol,
            timeframe=self._book_tf(), timestamp=ts, name=name, value=float(value),
            direction=Direction.NEUTRAL, strength=self._clamp01(float(strength)),
            reliability=self.reliability, meta=meta,
        )

    @staticmethod
    def _book_tf():
        from aimos.core.schemas import Timeframe
        return Timeframe.M1  # book aggregates persist at 1-minute granularity (§4.2)


__all__ = ["LiquidityEngine"]
