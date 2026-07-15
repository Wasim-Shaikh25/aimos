"""P4 Breakout (§7.2). Regime {BREAKOUT}.

Entry = stop-order entry_atr_beyond×ATR past the broken level; SL = the prior
range midpoint; TP = range height projected from the breakout.

SPEC-GAP (§7.2 P4): the exact "prior compression range" isn't carried in
MarketUnderstanding — we approximate the range as [support, resistance] from
key_levels, its midpoint as the SL, and its height as the TP projection. The
book-imbalance opposition veto uses the fused direction_bias (Layer 3 gets no
raw book).
"""

from __future__ import annotations

from aimos.core.schemas import (
    Action,
    Direction,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class Breakout(ExecutionPlugin):
    name = "Breakout"
    required_regimes = {Regime.BREAKOUT}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        kl = mu.key_levels
        atr = _f(kl.get("atr"))
        highs = kl.get("swing_highs") or []
        lows = kl.get("swing_lows") or []
        if atr is None or atr <= 0 or not highs or not lows:
            return None
        resistance = max(float(x) for x in highs)
        support = min(float(x) for x in lows)
        mid_range = (resistance + support) / 2.0
        height = resistance - support
        if height <= 0:
            return None

        beyond = float(self.cfg["entry_atr_beyond"]) * atr
        long = mu.direction_bias is Direction.BULLISH
        if long:
            entry = resistance + beyond
            stop = mid_range
            tp = entry + height
            action = Action.LONG
        elif mu.direction_bias is Direction.BEARISH:
            entry = support - beyond
            stop = mid_range
            tp = entry - height
            action = Action.SHORT
        else:
            return None

        risk = abs(entry - stop)
        if risk <= 0:
            return None
        rr = abs(tp - entry) / risk
        regime_prob = mu.regime_probs.get(mu.regime.value, 1.0)
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence * regime_prob,
            reasons=[f"breakout {action.value}: entry {entry:.2f} range {height:.2f}"],
        )


def _f(x):
    return float(x) if x is not None else None


__all__ = ["Breakout"]
