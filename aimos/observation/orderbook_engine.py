"""Order Book engine (§5.6, card P2-T4).

Consumes the aggregate window (§4.2). Emits book_imbalance from the mean of the
last N snapshots.

SPEC-GAP (§5.6 rules 2-3): bid_wall/ask_wall and book_absorption need raw L2
levels, which ``MarketContext.orderbook_window`` (§25.1) does not carry — they
arrive with the streaming feed (card P2-T7); ``data.orderbook.detect_walls``
(with spoof flag) does the detection where levels exist. With only aggregates,
this engine emits book_imbalance.
"""

from __future__ import annotations

from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


class OrderBookEngine(ObservationEngine):
    name = "orderbook_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        window = ctx.orderbook_window
        oc = self.cfg["orderbook"]
        n = int(oc["imbalance_window"])
        if len(window) < 1:
            return []
        recent = window[-n:]
        mean_imb = sum(b.imbalance for b in recent) / len(recent)
        if mean_imb == 0:
            return []
        ts = window[-1].timestamp
        direction = Direction.BULLISH if mean_imb > 0 else Direction.BEARISH
        return [
            Evidence(
                source=f"{self.name}.book_imbalance", symbol=ctx.symbol,
                timeframe=Timeframe.M1, timestamp=ts, name="book_imbalance",
                value=float(mean_imb), direction=direction,
                strength=self._clamp01(abs(mean_imb)), reliability=self.reliability,
                meta={"n_snapshots": len(recent)},
            )
        ]


__all__ = ["OrderBookEngine"]
