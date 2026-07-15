"""Execution layer orchestration (§25.4 order-of-operations, card P4-T1).

decide: plugins propose → evaluator selects → sizer sets size (+capacity MIN) →
risk manager gates → final TradePlan. RiskOff/NO_TRADE is always a candidate.
If sizing or a risk gate fails, the plan becomes NO_TRADE with a reason.
"""

from __future__ import annotations

from typing import Any, Optional

from aimos.core.normalize import PCT
from aimos.core.schemas import Action, ExecContext, MarketUnderstanding, TradePlan
from aimos.execution.evaluator import Evaluator
from aimos.execution.plugins import build_plugins
from aimos.execution.position_sizer import PositionSizer, SizingInputs
from aimos.execution.risk_manager import RiskManager, RiskState


class ExecutionLayer:
    def __init__(self, params: Any) -> None:
        self.params = params
        exec_cfg = params.execution.model_dump()
        self.plugins = build_plugins(params)
        self.evaluator = Evaluator(exec_cfg)
        self.sizer = PositionSizer(exec_cfg)
        self.risk_manager = RiskManager(exec_cfg, params.capacity.model_dump())

    def decide(
        self,
        mu: MarketUnderstanding,
        ctx: ExecContext,
        sizing_inputs: Optional[SizingInputs] = None,
        risk_state: Optional[RiskState] = None,
    ) -> TradePlan:
        # 1. candidates
        candidates: list[TradePlan] = []
        for plugin in self.plugins:
            if not plugin.can_trade(mu):
                continue
            plan = plugin.propose(mu, ctx)
            if plan is not None:
                candidates.append(plan)
        if not candidates:  # RiskOff should always propose, but be safe
            candidates.append(TradePlan(plugin="RiskOff", symbol=mu.symbol, action=Action.NO_TRADE))

        # 2. evaluator selects
        winner = self.evaluator.evaluate(candidates, mu)
        if winner.action is Action.NO_TRADE:
            return winner

        # 3. sizer (+ capacity MIN)
        result = self.sizer.size(winner, ctx, sizing_inputs or SizingInputs())
        if result.rejected:
            return TradePlan(plugin=winner.plugin, symbol=mu.symbol, action=Action.NO_TRADE,
                             reasons=[*winner.reasons, *result.reasons])

        # 4. risk manager gates
        state = risk_state or RiskState()
        new_risk_pct = self._new_risk_pct(winner, ctx)
        decision = self.risk_manager.check(winner, mu, ctx, state, new_risk_pct)
        return decision.plan

    @staticmethod
    def _new_risk_pct(plan: TradePlan, ctx: ExecContext) -> float:
        if not plan.size_quote or not plan.entry or plan.stop_loss is None or ctx.equity_usdt <= 0:
            return 0.0
        frac_risk = abs(plan.entry - plan.stop_loss) / plan.entry
        risk_quote = plan.size_quote * frac_risk
        return risk_quote / ctx.equity_usdt * PCT


__all__ = ["ExecutionLayer"]
