"""P3 Pullback (§7.2). Regimes {TRENDING_UP, TRENDING_DOWN}.

Only when price is within ema_proximity_atr×ATR of EMA(50) AND behavior is
CONTINUATION. Entry = limit at the EMA level; SL = sl_atr_beyond×ATR beyond
entry; TP = last swing extreme; require rr ≥ min_rr else None.
"""

from __future__ import annotations

from aimos.core.schemas import (
    Action,
    Behavior,
    Direction,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class Pullback(ExecutionPlugin):
    name = "Pullback"
    required_regimes = {Regime.TRENDING_UP, Regime.TRENDING_DOWN}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        if mu.behavior is not Behavior.CONTINUATION:
            return None
        kl = mu.key_levels
        ema = _f(kl.get("ema50"))
        price = _f(kl.get("price"))
        atr = _f(kl.get("atr"))
        if ema is None or price is None or atr is None or atr <= 0:
            return None
        if abs(price - ema) > float(self.cfg["ema_proximity_atr"]) * atr:
            return None

        long = mu.regime is Regime.TRENDING_UP
        beyond = float(self.cfg["sl_atr_beyond"]) * atr
        if long:
            entry, stop = ema, ema - beyond
            tp = _extreme(kl.get("swing_highs"), hi=True)
            action = Action.LONG
        else:
            entry, stop = ema, ema + beyond
            tp = _extreme(kl.get("swing_lows"), hi=False)
            action = Action.SHORT
        if tp is None:
            return None

        risk = abs(entry - stop)
        reward = abs(tp - entry)
        if risk <= 0:
            return None
        rr = reward / risk
        if rr < float(self.cfg["min_rr"]):
            return None
        regime_prob = mu.regime_probs.get(mu.regime.value, 1.0)
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence * regime_prob,
            reasons=[f"pullback to EMA {ema:.2f}, rr {rr:.2f}"],
        )


def _f(x):
    return float(x) if x is not None else None


def _extreme(levels, hi: bool):
    if not levels:
        return None
    vals = [float(x) for x in levels]
    return max(vals) if hi else min(vals)


__all__ = ["Pullback"]
