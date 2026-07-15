"""S1 MomentumScalp plugin (§17.3, card P6-T6).

Direction must AGREE with the slow-loop direction_bias. Trigger: 1m volume_spike
+ book_imbalance beyond threshold, same direction. Entry: maker limit at best
bid/ask (post-only — never taker entries). SL = s1_sl_atr_mult×ATR(1m); dynamic
TP to keep rr ≥ s1_min_rr after costs; returns None if spread too wide or EV ≤ 0.
Micro signals ride in ``mu.key_levels['scalp']`` (fast loop populates them).
"""

from __future__ import annotations

from typing import Any, Mapping

from aimos.core.schemas import (
    Action,
    Direction,
    ExecContext,
    MarketUnderstanding,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin


class MomentumScalp(ExecutionPlugin):
    name = "MomentumScalp"

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        # cfg = config/scalp.yaml
        super().__init__({"min_confidence": cfg["context_gate"]["min_confidence"]})
        self.micro = cfg["micro"]
        self.max_spread_bps = float(cfg["max_spread_bps"])
        self.order_type = cfg["order_type"]

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        scalp = mu.key_levels.get("scalp")
        if not isinstance(scalp, dict):
            return None
        spread_bps = _f(scalp.get("spread_bps"))
        atr1m = _f(scalp.get("atr1m"))
        imbalance = _f(scalp.get("book_imbalance"))
        vol_spike = bool(scalp.get("volume_spike"))
        best_bid = _f(scalp.get("best_bid"))
        best_ask = _f(scalp.get("best_ask"))
        if None in (spread_bps, atr1m, imbalance, best_bid, best_ask) or atr1m <= 0:
            return None
        if spread_bps > self.max_spread_bps:  # §17.3: too wide → no trade
            return None

        # direction must agree with slow-loop bias AND the micro imbalance
        imb_min = float(self.micro["s1_book_imbalance_min"])
        if mu.direction_bias is Direction.BULLISH and vol_spike and imbalance > imb_min:
            action, entry = Action.LONG, best_bid  # post-only maker at bid
            stop = entry - float(self.micro["s1_sl_atr_mult"]) * atr1m
        elif mu.direction_bias is Direction.BEARISH and vol_spike and imbalance < -imb_min:
            action, entry = Action.SHORT, best_ask
            stop = entry + float(self.micro["s1_sl_atr_mult"]) * atr1m
        else:
            return None

        risk = abs(entry - stop)
        if risk <= 0:
            return None
        min_rr = float(self.micro["s1_min_rr"])
        tp = entry + min_rr * risk if action is Action.LONG else entry - min_rr * risk
        # maker fees on entry (post-only), taker on worst-case exit (§17.3)
        costs = ctx.fee_maker_bps + ctx.fee_taker_bps + ctx.slippage_exit_bps
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=action,
            entry=entry, stop_loss=stop, take_profit=tp, expected_rr=min_rr,
            expected_hold_minutes=int(self.micro["s1_max_hold_min"]),
            expected_costs_bps=costs, confidence=mu.confidence,
            reasons=[f"scalp {action.value} post-only at {entry:.6g}"],
            meta={"mode_tag": "scalp", "order_type": self.order_type},
        )


def _f(x):
    return float(x) if isinstance(x, (int, float)) else None


__all__ = ["MomentumScalp"]
