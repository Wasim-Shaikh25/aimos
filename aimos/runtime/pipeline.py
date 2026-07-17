"""Pipeline orchestrator + paper loop (§10.1, §25.8, §15.2, card P5-T1).

Per-symbol ticks run observation → intelligence → execution → journal, with:

* **PortfolioLock** — a single ``asyncio.Lock`` serializes the portfolio-touching
  stage (evaluator → sizer → risk → broker) across symbols, while observation and
  intelligence run freely in parallel (§25.8).
* **Per-engine isolation** — a raising engine is logged and skipped (run_all);
  evidence_coverage drops and confidence self-reduces (§6.7, §10.1).
* **Pause flags** — global or per-asset pause forces NO_TRADE while the pipeline
  KEEPS observing + journaling (safe pause, no blind spot, §15.2).
* **RUNTIME_HALT** — presence of the kill-switch file halts trading (§7.4 rule 5).

Not in the magic-number-linted layers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import structlog

from aimos.core.bus import EventBus, Topic
from aimos.core.clock import Clock, LiveClock
from aimos.core.schemas import (
    Action,
    DecisionRecord,
    ExecContext,
    MarketContext,
    MarketUnderstanding,
    TradePlan,
)
from aimos.execution.decide import ExecutionLayer
from aimos.execution.position_sizer import SizingInputs
from aimos.execution.risk_manager import RiskState
from aimos.intelligence.understand import IntelligenceLayer
from aimos.journal.journal import Journal
from aimos.observation.runner import build_engines, engines_reporting, run_all

log = structlog.get_logger(__name__)


@dataclass
class RuntimeState:
    global_pause: bool = False
    paused_assets: set[str] = field(default_factory=set)
    halted: bool = False


@dataclass
class TickResult:
    understanding: MarketUnderstanding
    plan: TradePlan
    decision_id: str
    forced_no_trade: bool
    evidences: list = field(default_factory=list)  # raw Evidence for the engines view


class PipelineOrchestrator:
    def __init__(
        self,
        params: Any,
        clock: Optional[Clock] = None,
        bus: Optional[EventBus] = None,
        journal: Optional[Journal] = None,
        halt_file: str = "RUNTIME_HALT",
    ) -> None:
        self.params = params
        self.clock = clock or LiveClock()
        self.bus = bus or EventBus()
        self.obs_engines = build_engines(params, self.clock)
        self.intel = IntelligenceLayer(params)
        self.execution = ExecutionLayer(params)
        self.journal = journal or Journal(":memory:")
        self.state = RuntimeState()
        self.lock = asyncio.Lock()  # PortfolioLock
        self.halt_file = Path(halt_file)

    # -- pause / halt controls (shared with UI + Telegram, §15.2) -----------

    def pause(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self.state.global_pause = True
        else:
            self.state.paused_assets.add(symbol)

    def resume(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self.state.global_pause = False
        else:
            self.state.paused_assets.discard(symbol)

    def is_paused(self, symbol: str) -> bool:
        return self.state.global_pause or symbol in self.state.paused_assets

    def check_halt(self) -> bool:
        if self.halt_file.exists():
            self.state.halted = True
        return self.state.halted

    # -- one tick ------------------------------------------------------------

    async def tick(
        self,
        ctx: MarketContext,
        exec_ctx: ExecContext,
        sizing_inputs: Optional[SizingInputs] = None,
        risk_state: Optional[RiskState] = None,
        mode: str = "paper",
    ) -> TickResult:
        symbol = ctx.symbol
        # observation + intelligence run outside the lock (parallel-safe)
        bundle, mu = self._observe_understand(ctx)

        forced = False
        async with self.lock:  # portfolio-global stage serialized
            if self.check_halt() or self.is_paused(symbol):
                plan = self._forced_no_trade(mu)
                forced = True
            else:
                plan = self.execution.decide(mu, exec_ctx, sizing_inputs, risk_state)
            decision_id = f"{symbol}-{ctx.now.isoformat()}"
            self.journal.write_decision(DecisionRecord(
                timestamp=ctx.now, symbol=symbol, understanding=mu,
                candidates=[], chosen=plan, mode=mode, decision_id=decision_id,
            ))
            self.bus.publish(Topic.DECISION, {"decision_id": decision_id, "symbol": symbol,
                                              "action": plan.action.value})
            if plan.action is not Action.NO_TRADE:
                self.bus.publish(Topic.TRADE_OPENED, {"symbol": symbol, "plan": plan.plugin})

        return TickResult(mu, plan, decision_id, forced, list(bundle.evidences))

    def _observe_understand(self, ctx: MarketContext):
        bundle = run_all(self.obs_engines, ctx)  # per-engine isolation (§10.1)
        reporting = len(engines_reporting(bundle))
        return bundle, self.intel.understand(bundle, reporting)

    def analyze(
        self,
        ctx: MarketContext,
        exec_ctx: ExecContext,
        sizing_inputs: Optional[SizingInputs] = None,
        risk_state: Optional[RiskState] = None,
    ) -> TickResult:
        """Observe → understand → decide WITHOUT journaling (for per-venue display).

        Same reasoning as ``tick`` but no lock/pause/halt/journal — used to compute
        a per-venue MarketUnderstanding + action for the dashboard columns without
        colliding decision ids or double-journaling (§3.1 multi-venue).
        """
        bundle, mu = self._observe_understand(ctx)
        plan = self.execution.decide(mu, exec_ctx, sizing_inputs, risk_state)
        return TickResult(mu, plan, "", False, list(bundle.evidences))

    @staticmethod
    def _forced_no_trade(mu: MarketUnderstanding) -> TradePlan:
        return TradePlan(
            plugin="RiskOff", symbol=mu.symbol, action=Action.NO_TRADE,
            reasons=["paused/halted — observing only, trading suppressed (§15.2)"],
        )


__all__ = ["PipelineOrchestrator", "RuntimeState", "TickResult"]
