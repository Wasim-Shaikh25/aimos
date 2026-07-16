"""P8 CrossExchangeArb (§7.2 P8, §5.11). Any regime.

Consumes the ``price_dislocation`` evidence surfaced into
``MarketUnderstanding.key_levels["dislocation"]`` (bps + cheap/rich venue).
When the USD-converted dislocation exceeds round-trip costs + a safety margin it
proposes a simultaneous **buy(cheap) / sell(rich)** capture: the TradePlan is the
LONG leg on the cheap venue; ``meta.cross_venue`` + ``meta.sell_venue`` tell the
router to place the offsetting short on the rich venue. rr is computed from the
net spread capture vs a convergence-failure stop.

Market-neutral, so it ignores regime/coin_health (``required_regimes`` empty).

SPEC-GAP (§16.1 line 1123): the "asset ∈ common(min_venues=2)" intersection rule
is enforced upstream — ``compute_dislocation`` returns nothing for < 2 venues, so
a dislocation with two distinct named venues *is* the proof both legs exist. The
plugin contract carries no live ``Registry`` handle, so we gate on that evidence
rather than re-querying ``registry.venues(base)`` inside ``can_trade``.
"""

from __future__ import annotations

from aimos.core.normalize import BPS
from aimos.core.schemas import (
    Action,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class CrossExchangeArb(ExecutionPlugin):
    name = "CrossExchangeArb"
    required_regimes: set[Regime] = set()  # market-neutral: any regime (§7.2 P8)

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        disl = mu.key_levels.get("dislocation")
        price = _f(mu.key_levels.get("price"))
        if not isinstance(disl, dict) or price is None or price <= 0:
            return None

        buy_venue = disl.get("buy_venue")
        sell_venue = disl.get("sell_venue")
        bps = _f(disl.get("bps"))
        if bps is None or not buy_venue or not sell_venue or buy_venue == sell_venue:
            return None  # need a real two-venue spread (§16.1 intersection)

        # net capture = gross dislocation − round-trip costs − safety margin (§7.2 P8)
        costs_bps = self.estimate_costs_bps(ctx)
        margin_bps = float(self.cfg["extra_margin_bps"])
        net_bps = bps - costs_bps - margin_bps
        if net_bps <= 0:
            return None  # spread doesn't clear fees + slippage + margin → skip

        stop_bps = float(self.cfg["stop_bps"])
        if stop_bps <= 0:
            return None
        entry = price
        take_profit = entry * (1 + net_bps / BPS)   # convergence captures net spread
        stop_loss = entry * (1 - stop_bps / BPS)     # divergence past this → bail
        rr = net_bps / stop_bps

        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=Action.LONG,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit, expected_rr=rr,
            expected_hold_minutes=int(self.cfg["hold_minutes"]),
            expected_costs_bps=costs_bps,
            confidence=float(self.cfg["arb_confidence"]),
            reasons=[
                f"cross-exchange arb: buy {buy_venue} / sell {sell_venue}, "
                f"dislocation {bps:.1f}bps net {net_bps:.1f}bps"
            ],
            meta={
                "cross_venue": True, "buy_venue": buy_venue, "sell_venue": sell_venue,
                "dislocation_bps": bps, "net_capture_bps": net_bps,
            },
        )


def _f(x):
    return float(x) if x is not None else None


__all__ = ["CrossExchangeArb"]
