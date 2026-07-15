"""P1 RiskOff (§7.2). Always first, always enabled.

Proposes NO_TRADE with the evaluator's baseline score, making "do nothing" a
first-class candidate every other plugin must beat (§7.3).
"""

from __future__ import annotations

from aimos.core.schemas import Action, ExecContext, MarketUnderstanding, TradePlan
from aimos.execution.base_plugin import ExecutionPlugin


class RiskOff(ExecutionPlugin):
    name = "RiskOff"

    def can_trade(self, mu: MarketUnderstanding) -> bool:
        return True

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=Action.NO_TRADE,
            reasons=["do-nothing baseline"],
        )


__all__ = ["RiskOff"]
