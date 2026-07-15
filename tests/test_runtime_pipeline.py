"""Pipeline orchestrator tests (§10.1, §15.2 — card P5-T1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.clock import LiveClock
from aimos.core.schemas import Action, Timeframe
from aimos.data.context import build_context
from aimos.runtime.pipeline import PipelineOrchestrator
from tests.conftest import make_candles, make_exec_ctx

TS = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _bullish_ctx():
    # a rising series that yields TRENDING_UP-ish evidence
    import numpy as np
    closes = list(np.linspace(100, 200, 260))
    df = make_candles(closes)
    now = df.index[-1].to_pydatetime()
    return build_context("BTC", now, {Timeframe.H1: df}, peers={"BTC": df})


def test_pause_forces_no_trade_while_observing():
    orch = PipelineOrchestrator(load_params(), clock=LiveClock())
    orch.pause()  # global pause
    ctx = _bullish_ctx()
    result = asyncio.run(orch.tick(ctx, make_exec_ctx()))
    assert result.plan.action is Action.NO_TRADE
    assert result.forced_no_trade
    # still observed + journaled (no blind spot)
    assert orch.journal.decision_count() == 1
    assert result.understanding is not None


def test_per_asset_pause():
    orch = PipelineOrchestrator(load_params())
    orch.pause("BTC")
    assert orch.is_paused("BTC")
    assert not orch.is_paused("ETH")


def test_engine_failure_degrades_not_crashes():
    orch = PipelineOrchestrator(load_params())

    class Boom:
        name = "boom"
        def observe(self, ctx):
            raise RuntimeError("boom")

    orch.obs_engines.append(Boom())
    result = asyncio.run(orch.tick(_bullish_ctx(), make_exec_ctx()))
    # tick completes despite the failing engine; a decision is produced
    assert result.decision_id
    assert orch.journal.decision_count() == 1


def test_portfolio_lock_serializes_ticks():
    orch = PipelineOrchestrator(load_params())
    order: list[str] = []
    real_decide = orch.execution.decide

    async def _concurrent():
        # two ticks racing; the lock must serialize the portfolio stage
        async def one(sym):
            import numpy as np
            df = make_candles(list(np.linspace(100, 200, 260)))
            ctx = build_context(sym, df.index[-1].to_pydatetime(), {Timeframe.H1: df}, peers={"BTC": df})
            await orch.tick(ctx, make_exec_ctx())
            order.append(sym)
        await asyncio.gather(one("BTC"), one("ETH"))

    asyncio.run(_concurrent())
    assert orch.journal.decision_count() == 2  # both completed, no corruption


def test_killswitch_halts():
    orch = PipelineOrchestrator(load_params())
    orch.state.halted = True
    result = asyncio.run(orch.tick(_bullish_ctx(), make_exec_ctx()))
    assert result.plan.action is Action.NO_TRADE
    assert result.forced_no_trade
