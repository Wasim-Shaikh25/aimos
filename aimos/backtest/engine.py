"""Event-driven backtest engine (§9.1, §25.7, card P4-T7).

Replays the EXACT production pipeline (same observation → intelligence →
execution) with a BacktestClock and PaperBroker. Anti-lookahead by construction:

* observation windows end at ``t`` (build_context trims to ≤ now),
* fills execute on the NEXT bar (``broker.step`` is called with bar ``t+1``),
* no wall-clock reads (BacktestClock) → replays are byte-identical (§13 test 7).

Each run declares an ``engine_profile`` (§25.7) whose enabled-engine count is the
evidence_coverage denominator, so confidence is comparable across profiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import structlog

from aimos.backtest import costs as cost_mod
from aimos.backtest.metrics import Metrics, compute_metrics
from aimos.core.clock import BacktestClock
from aimos.core.schemas import (
    Action,
    CapacityCaps,
    DecisionRecord,
    ExecContext,
    Timeframe,
)
from aimos.data.context import build_context
from aimos.execution.decide import ExecutionLayer
from aimos.execution.broker.paper import PaperBroker
from aimos.execution.position_sizer import SizingInputs
from aimos.execution.risk_manager import RiskState
from aimos.intelligence.understand import IntelligenceLayer
from aimos.journal.journal import Journal
from aimos.observation.runner import build_engines, engines_reporting, run_all

log = structlog.get_logger(__name__)

# no_book profile: the 5 book/funding/venue engines can't report → denominator 8
_NO_BOOK_COVERAGE = 8


@dataclass
class BacktestResult:
    equity_curve: list[float]
    n_decisions: int
    n_no_trade: int
    metrics: Metrics
    journal: Journal
    broker: PaperBroker

    @property
    def no_trade_rate(self) -> float:
        return self.n_no_trade / self.n_decisions if self.n_decisions else 0.0


class BacktestEngine:
    def __init__(
        self,
        params: Any,
        symbol: str,
        starting_equity: float = 10_000.0,
        engine_profile: str = "no_book",
        journal_path: str = ":memory:",
    ) -> None:
        self.params = params
        self.symbol = symbol
        self.profile = engine_profile
        self.coverage = _NO_BOOK_COVERAGE if engine_profile == "no_book" else int(
            params.intelligence.model_dump()["coverage_engines"]
        )
        self.clock = BacktestClock()
        self.obs_engines = build_engines(params, self.clock)
        self.intel = IntelligenceLayer(params)
        self.execution = ExecutionLayer(params)
        self.cost = cost_mod.from_config(params.costs.model_dump())
        self.broker = PaperBroker(starting_equity, self.cost)
        self.journal = Journal(journal_path)
        self._caps = self._build_caps(params)
        self._depth_frac = float(params.costs.model_dump()["volume_proxy_depth_frac"])
        self._primary = params.exchanges["primary"]

    def run(self, candles: pd.DataFrame, warmup: int = 200) -> BacktestResult:
        equity_curve: list[float] = []
        n_decisions = 0
        n_no_trade = 0
        n = len(candles)
        for i in range(warmup, n - 1):  # need bar i+1 to fill
            bar_time = candles.index[i].to_pydatetime()
            self.clock.set(bar_time)
            window = candles.iloc[: i + 1]  # data <= t (anti-lookahead)
            ctx = build_context(self.symbol, bar_time, {Timeframe.H1: window}, peers={"BTC": window})
            bundle = run_all(self.obs_engines, ctx)
            reporting = len(engines_reporting(bundle))
            mu = self.intel.understand(bundle, reporting, coverage_engines=self.coverage)

            exec_ctx = self._exec_ctx()
            plan = self.execution.decide(
                mu, exec_ctx, self._sizing_inputs(window.iloc[-1]),
                RiskState(open_positions=len(self.broker.positions())),
            )
            n_decisions += 1
            if plan.action is Action.NO_TRADE:
                n_no_trade += 1
            else:
                self.broker.place(plan)

            next_bar = candles.iloc[i + 1]
            self.broker.step(self.symbol, next_bar.to_dict(), candles.index[i + 1].to_pydatetime())

            self.journal.write_decision(DecisionRecord(
                timestamp=bar_time, symbol=self.symbol, understanding=mu,
                candidates=[], chosen=plan, mode="backtest",
                decision_id=f"{self.symbol}-{bar_time.isoformat()}",
            ))
            self._drain_outcomes()
            equity_curve.append(self.broker.equity())

        days = max((candles.index[-1] - candles.index[warmup]).days, 1)
        metrics = compute_metrics(
            equity_curve, self.broker.closed_trades_r, n_decisions, n_no_trade, days=days
        )
        return BacktestResult(equity_curve, n_decisions, n_no_trade, metrics, self.journal, self.broker)

    # -- context builders ----------------------------------------------------

    def _exec_ctx(self) -> ExecContext:
        c = self.params.costs.model_dump()
        return ExecContext(
            equity_usdt=self.broker.equity(),
            open_positions=self.broker.positions(),
            portfolio_heat_pct=0.0,
            fee_taker_bps=float(c["taker_bps"]),
            fee_maker_bps=float(c["maker_bps"]),
            slippage_entry_bps=float(c["slip_base_bps"]),
            slippage_exit_bps=float(c["slip_base_bps"]),
            venue=self._primary,
            caps=self._caps,
        )

    def _sizing_inputs(self, last_bar) -> SizingInputs:
        bar_vol_quote = float(last_bar["volume"]) * float(last_bar["close"])
        depth = self._depth_frac * bar_vol_quote  # §9.2 volume-proxy depth
        return SizingInputs(volume_24h_usd=bar_vol_quote, book_depth_1pct_usd=depth)

    def _drain_outcomes(self) -> None:
        """Persist closed trade outcomes; never let a journal failure crash the engine."""
        for outcome in self.broker.drain_outcomes():
            try:
                self.journal.write_outcome(outcome)
            except Exception:  # noqa: BLE001
                log.error("journal_write_outcome_failed", decision_id=outcome.decision_id, exc_info=True)

    @staticmethod
    def _build_caps(params) -> CapacityCaps:
        cap = params.capacity.model_dump()
        return CapacityCaps(
            max_equity_pct_per_asset=float(cap["max_equity_pct_per_asset"]),
            max_pct_of_24h_volume=float(cap["max_pct_of_24h_volume"]),
            max_pct_of_book_depth=float(cap["max_pct_of_book_depth"]),
            max_exit_slippage_bps=float(cap["max_exit_slippage_bps"]),
            stress_exit_bps=float(cap["stress_exit_bps"]),
        )


__all__ = ["BacktestEngine", "BacktestResult"]
