"""P2 TrendFollowing (§7.2). Regimes {TRENDING_UP, TRENDING_DOWN}.

Reproduces §25.9 step 7 geometry exactly: entry = mid; SL = nearest opposing
swing ∓ sl_atr_buffer×ATR; TP = tp_rr·R; confidence = mu.confidence × regime_prob.
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


class TrendFollowing(ExecutionPlugin):
    name = "TrendFollowing"
    required_regimes = {Regime.TRENDING_UP, Regime.TRENDING_DOWN}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        long = mu.regime is Regime.TRENDING_UP
        want = Direction.BULLISH if long else Direction.BEARISH
        if mu.direction_bias is not want:  # require bias agreement
            return None

        levels = mu.key_levels
        atr = float(levels.get("atr", 0.0))
        entry = self._mid(mu, ctx)
        if entry is None or atr <= 0:
            return None

        buffer = float(self.cfg["sl_atr_buffer"]) * atr
        if long:
            swing_low = _nearest(levels.get("swing_lows"), below=entry)
            if swing_low is None:
                return None
            stop = swing_low - buffer
            action = Action.LONG
        else:
            swing_high = _nearest(levels.get("swing_highs"), below=None, above=entry)
            if swing_high is None:
                return None
            stop = swing_high + buffer
            action = Action.SHORT

        r = abs(entry - stop)
        if r <= 0:
            return None
        tp_rr = float(self.cfg["tp_rr"])
        tp = entry + tp_rr * r if long else entry - tp_rr * r
        regime_prob = mu.regime_probs.get(mu.regime.value, 1.0)

        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp,
            expected_rr=tp_rr,
            expected_hold_minutes=int(mu.horizon_minutes * int(self.cfg["hold_horizon_mult"])),
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence * regime_prob,
            reasons=[f"trend-follow {action.value}: entry {entry:.2f} SL {stop:.2f} TP {tp:.2f}"],
        )

    @staticmethod
    def _mid(mu: MarketUnderstanding, ctx: ExecContext) -> float | None:
        # entry = current mid; provided via key_levels["price"] or ctx (SPEC-GAP:
        # plugins get no raw price, so observation exports it in key_levels).
        price = mu.key_levels.get("price")
        return float(price) if price is not None else None


def _nearest(levels, below=None, above=None):
    """Nearest level below/above a reference (opposing swing selection)."""
    if not levels:
        return None
    vals = [float(x) for x in levels]
    if below is not None:
        candidates = [v for v in vals if v < below]
        return max(candidates) if candidates else max(vals)
    if above is not None:
        candidates = [v for v in vals if v > above]
        return min(candidates) if candidates else min(vals)
    return vals[-1]


__all__ = ["TrendFollowing"]
