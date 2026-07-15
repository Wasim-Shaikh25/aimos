"""P7 FundingRate (§7.2). Any regime.

Only when a funding_extreme signal with |z| > funding_z_min is present and the
fused direction agrees with the contrarian side. Delta-light: enter contrarian,
TP at funding normalization, SL funding_z... 1.5×ATR.

SPEC-GAP: funding z is evidence, but Layer 3 sees only MarketUnderstanding — so
observation surfaces the funding z into ``key_levels['funding_z']`` for the plugin.
"""

from __future__ import annotations

from aimos.core.schemas import (
    Action,
    Direction,
    ExecContext,
    MarketUnderstanding,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class FundingRate(ExecutionPlugin):
    name = "FundingRate"

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        kl = mu.key_levels
        funding_z = _f(kl.get("funding_z"))
        price = _f(kl.get("price"))
        atr = _f(kl.get("atr"))
        if funding_z is None or price is None or atr is None or atr <= 0:
            return None
        if abs(funding_z) < float(self.cfg["funding_z_min"]):
            return None

        # contrarian to funding: positive funding (crowded longs) → fade short
        contrarian = Direction.BEARISH if funding_z > 0 else Direction.BULLISH
        if mu.direction_bias is not contrarian:
            return None

        sl_mult = float(self.cfg["sl_atr_mult"])
        if contrarian is Direction.BULLISH:
            entry, stop = price, price - sl_mult * atr
            tp = price + sl_mult * atr  # symmetric target at normalization
            action = Action.LONG
        else:
            entry, stop = price, price + sl_mult * atr
            tp = price - sl_mult * atr
            action = Action.SHORT

        risk = abs(entry - stop)
        rr = abs(tp - entry) / risk if risk > 0 else 0.0
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence,
            reasons=[f"funding fade {action.value}: z={funding_z:.2f}"],
        )


def _f(x):
    return float(x) if isinstance(x, (int, float)) else None


__all__ = ["FundingRate"]
