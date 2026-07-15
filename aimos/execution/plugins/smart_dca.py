"""P6 SmartDCA (§7.2). Regimes {CRASH, RECOVERY}; behavior {CAPITULATION, PANIC}.

Laddered accumulation: tranches at configured −ATR offsets from mid with a size
split; basket-level stop; TP at the 30-day VWAP. The ladder rides in
``TradePlan.meta['ladder']``.
"""

from __future__ import annotations

from typing import Any, Mapping

from aimos.core.normalize import PCT
from aimos.core.schemas import (
    Action,
    Behavior,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin

_CAPITULATION_BEHAVIORS = {Behavior.CAPITULATION, Behavior.PANIC}


def build_ladder(mid: float, atr: float, offsets: list, size_pcts: list) -> list[dict]:
    """Tranche prices at mid + offset×ATR with the size split (§7.2 P6)."""
    return [
        {"price": mid + float(off) * atr, "size_pct": float(pct)}
        for off, pct in zip(offsets, size_pcts)
    ]


class SmartDCA(ExecutionPlugin):
    name = "SmartDCA"
    required_regimes = {Regime.CRASH, Regime.RECOVERY}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        if mu.behavior not in _CAPITULATION_BEHAVIORS:
            return None
        kl = mu.key_levels
        mid = _f(kl.get("price"))
        atr = _f(kl.get("atr"))
        if mid is None or atr is None or atr <= 0:
            return None

        ladder = build_ladder(mid, atr, self.cfg["tranche_atr_offsets"], self.cfg["tranche_size_pct"])
        basket_stop_pct = float(self.cfg["basket_stop_pct"])
        # weighted-average entry across the ladder
        total_pct = sum(t["size_pct"] for t in ladder)
        avg_entry = sum(t["price"] * t["size_pct"] for t in ladder) / total_pct if total_pct else mid
        stop = avg_entry * (1.0 + basket_stop_pct / PCT)
        tp = _f(kl.get("vwap30")) or avg_entry * (1.0 + abs(basket_stop_pct) / PCT)

        risk = abs(avg_entry - stop)
        rr = abs(tp - avg_entry) / risk if risk > 0 else 0.0
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=Action.LONG,
            entry=ladder[0]["price"], stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence,
            reasons=[f"SmartDCA ladder {len(ladder)} tranches, avg {avg_entry:.4g}"],
            meta={"ladder": ladder},
        )


def _f(x):
    return float(x) if isinstance(x, (int, float)) else None


__all__ = ["SmartDCA", "build_ladder"]
