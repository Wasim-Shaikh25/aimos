"""P5 MeanReversion / RangeTrading (§7.2). Regime {RANGING}.

Entry = limit at the range boundary when p_up agrees with the bounce direction;
SL = sl_atr_beyond×ATR beyond the boundary; TP = mid-range. Requires
coin_health ≥ min_coin_health (ranging + thin book = chop death).
"""

from __future__ import annotations

from aimos.core.normalize import HALF
from aimos.core.schemas import (
    Action,
    Direction,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class MeanReversion(ExecutionPlugin):
    name = "MeanReversion"
    required_regimes = {Regime.RANGING}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        kl = mu.key_levels
        atr = _f(kl.get("atr"))
        price = _f(kl.get("price"))
        highs = kl.get("swing_highs") or []
        lows = kl.get("swing_lows") or []
        if atr is None or price is None or atr <= 0 or not highs or not lows:
            return None
        resistance = max(float(x) for x in highs)
        support = min(float(x) for x in lows)
        mid_range = (resistance + support) * HALF
        beyond = float(self.cfg["sl_atr_beyond"]) * atr

        # bounce long off support when bias bullish; short off resistance when bearish
        if mu.direction_bias is Direction.BULLISH:
            entry, stop, tp = support, support - beyond, mid_range
            action = Action.LONG
        elif mu.direction_bias is Direction.BEARISH:
            entry, stop, tp = resistance, resistance + beyond, mid_range
            action = Action.SHORT
        else:
            return None

        risk = abs(entry - stop)
        reward = abs(tp - entry)
        if risk <= 0 or reward <= 0:
            return None
        rr = reward / risk
        regime_prob = mu.regime_probs.get(mu.regime.value, 1.0)
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence * regime_prob,
            reasons=[f"range fade {action.value} at {entry:.2f} → mid {tp:.2f}"],
        )


def _f(x):
    return float(x) if x is not None else None


__all__ = ["MeanReversion"]
