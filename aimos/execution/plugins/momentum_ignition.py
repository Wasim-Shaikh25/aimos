"""MomentumIgnition plugin (§23.11-B, card P5-T5). Own risk sub-book.

Entry window only: within ``entry_window_min`` of the ignition timestamp AND
price within ``ema9_atr_mult``×ATR(5m) of the 5m EMA9 (buy the first pullback,
never the vertical candle). Requires the classifier organic, behavior ∉
{MANIPULATION, EUPHORIA}, confidence ≥ min. Ignition context (ts/organic/ema9/
atr5m) rides in ``mu.key_levels['ignition']`` (runtime populates it).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from aimos.core.schemas import (
    Action,
    Behavior,
    Direction,
    ExecContext,
    MarketUnderstanding,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin

_BLOCKED_BEHAVIORS = {Behavior.MANIPULATION, Behavior.EUPHORIA}


class MomentumIgnition(ExecutionPlugin):
    name = "MomentumIgnition"

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        # cfg = config/ignition.yaml (has `plugin:` and `ignition_book:` blocks)
        super().__init__(cfg.get("plugin", {}))
        self.plugin_cfg = cfg["plugin"]
        self.book = cfg["ignition_book"]

    def can_trade(self, mu: MarketUnderstanding) -> bool:
        if mu.behavior in _BLOCKED_BEHAVIORS:
            return False
        return mu.confidence >= self.min_confidence

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        ign = mu.key_levels.get("ignition")
        if not isinstance(ign, dict) or not ign.get("organic"):
            return None
        ema9 = _f(ign.get("ema9"))
        atr5m = _f(ign.get("atr5m"))
        price = _f(ign.get("price")) or _f(mu.key_levels.get("price"))
        ts = ign.get("ts")
        if ema9 is None or atr5m is None or price is None or ts is None or atr5m <= 0:
            return None

        # entry window: within N minutes of ignition
        if mu.timestamp - ts > timedelta(minutes=int(self.plugin_cfg["entry_window_min"])):
            return None
        # price near the 5m EMA9 (first pullback, not the vertical candle)
        if abs(price - ema9) > float(self.plugin_cfg["ema9_atr_mult"]) * atr5m:
            return None

        # geometry — payoff carried by 3R+ winners (§23.11-B); tight sub-book risk
        entry = price
        stop = entry - atr5m  # 1×ATR(5m) below
        tp = entry + float(self.plugin_cfg["partial_at_r"]) * (entry - stop)  # ≥ +2R target
        if entry - stop <= 0:
            return None
        rr = (tp - entry) / (entry - stop)
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=Action.LONG,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=rr,
            expected_hold_minutes=int(self.plugin_cfg["max_hold_min"]),
            expected_costs_bps=self.estimate_costs_bps(ctx),
            confidence=mu.confidence,
            reasons=[f"ignition pullback entry {entry:.4g}, rr {rr:.2f}"],
            meta={"mode_tag": "ignition", "sub_book": dict(self.book),
                  "management": {"breakeven_r": self.plugin_cfg["breakeven_r"],
                                 "trail_atr_mult": self.plugin_cfg["trail_atr_mult"],
                                 "max_hold_min": self.plugin_cfg["max_hold_min"]}},
        )


def _f(x):
    return float(x) if isinstance(x, (int, float)) else None


__all__ = ["MomentumIgnition"]
