"""Paper-trading loop — real end-to-end entrypoint (§10.1, card P5-T1).

Wires a public-data source → PipelineOrchestrator → PaperBroker → (optional)
Telegram, driven by config feature flags. Needs NO exchange API keys: paper mode
reads PUBLIC candles and fills against the simulator.

Run it now, fully offline (no network, no keys):
    python -m aimos.runtime.paper_trader --offline --ticks 3

Live public data (still no API keys):
    AIMOS__FEATURES__LIVE_DATA=true python -m aimos.runtime.paper_trader --ticks 5

Telegram messages: set features.telegram_enabled + TELEGRAM_BOT_TOKEN env.
Not in the magic-number-linted layers.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import timezone
from typing import Optional

import structlog

from aimos.backtest import costs as cost_mod
from aimos.core.clock import LiveClock
from aimos.core.config import Params, load_params
from aimos.core.schemas import Action, CapacityCaps, ExecContext, Timeframe
from aimos.data.context import build_context
from aimos.data.live_source import CcxtPublicSource, SyntheticSource, base_of
from aimos.execution.broker.paper import PaperBroker
from aimos.execution.position_sizer import SizingInputs
from aimos.execution.risk_manager import RiskState
from aimos.runtime.pipeline import PipelineOrchestrator
from aimos.telegram.sink import TelegramSink

log = structlog.get_logger(__name__)


@dataclass
class PaperRunSummary:
    ticks: int = 0
    decisions: int = 0
    trades_opened: int = 0
    no_trades: int = 0
    final_equity: float = 0.0
    telegram_messages: list[str] = field(default_factory=list)


def _caps(params: Params) -> CapacityCaps:
    c = params.capacity.model_dump()
    return CapacityCaps(
        max_equity_pct_per_asset=float(c["max_equity_pct_per_asset"]),
        max_pct_of_24h_volume=float(c["max_pct_of_24h_volume"]),
        max_pct_of_book_depth=float(c["max_pct_of_book_depth"]),
        max_exit_slippage_bps=float(c["max_exit_slippage_bps"]),
        stress_exit_bps=float(c["stress_exit_bps"]),
    )


async def run_paper(
    params: Optional[Params] = None,
    offline: Optional[bool] = None,
    max_ticks: Optional[int] = None,
) -> PaperRunSummary:
    params = params or load_params()
    features = params.features.model_dump()
    paper = params.paper.model_dump()
    costs_cfg = params.costs.model_dump()

    live_data = features["live_data"] if offline is None else (not offline)
    ticks_limit = max_ticks if max_ticks is not None else int(paper["max_ticks"])
    symbols = list(paper["symbols"])
    tf = paper["timeframe"]
    bars = int(paper["history_bars"])
    loop_seconds = float(paper["loop_seconds"])

    clock = LiveClock()
    orch = PipelineOrchestrator(params, clock=clock)
    broker = PaperBroker(float(paper["starting_equity_usdt"]), cost_mod.from_config(costs_cfg))
    caps = _caps(params)

    from aimos.runtime.watchdog import Heartbeat
    heartbeat = Heartbeat(paper.get("heartbeat_path", "state/heartbeat"), clock=clock)

    sink: Optional[TelegramSink] = None
    if features["telegram_enabled"]:
        sink = TelegramSink()  # token from env; dry-run (logs) if no token
        sink.attach(orch.bus)
        sink.send("🤖 AIMOS paper trader started")

    source = CcxtPublicSource(paper["data_exchange"]) if live_data else SyntheticSource()

    summary = PaperRunSummary()
    tick = 0
    while ticks_limit == 0 or tick < ticks_limit:
        btc_df = source.fetch("BTC/USDT", tf, bars)  # peer for the correlation engine
        for symbol in symbols:
            df = source.fetch(symbol, tf, bars)
            if df.empty:
                continue
            now = df.index[-1].to_pydatetime().astimezone(timezone.utc)
            ctx = build_context(base_of(symbol), now, {Timeframe(tf): df}, peers={"BTC": btc_df})
            last = df.iloc[-1]
            exec_ctx = ExecContext(
                equity_usdt=broker.equity(), open_positions=broker.positions(),
                portfolio_heat_pct=0.0, fee_taker_bps=float(costs_cfg["taker_bps"]),
                fee_maker_bps=float(costs_cfg["maker_bps"]),
                slippage_entry_bps=float(costs_cfg["slip_base_bps"]),
                slippage_exit_bps=float(costs_cfg["slip_base_bps"]),
                venue=paper["data_exchange"], caps=caps,
            )
            depth = float(costs_cfg["volume_proxy_depth_frac"]) * float(last["volume"]) * float(last["close"])
            result = await orch.tick(
                ctx, exec_ctx,
                SizingInputs(volume_24h_usd=float(last["volume"]) * float(last["close"]),
                             book_depth_1pct_usd=depth),
                RiskState(open_positions=len(broker.positions())),
            )
            summary.decisions += 1
            if result.plan.action is Action.NO_TRADE:
                summary.no_trades += 1
            else:
                summary.trades_opened += 1
                broker.place(result.plan)
            broker.step(base_of(symbol), last.to_dict(), now)
            log.info("tick", symbol=symbol, regime=result.understanding.regime.value,
                     p_up=round(result.understanding.p_up, 3), action=result.plan.action.value)
        tick += 1
        summary.ticks = tick
        heartbeat.beat()  # watchdog liveness (§23.5)
        if live_data and (ticks_limit == 0 or tick < ticks_limit):
            await asyncio.sleep(loop_seconds)

    summary.final_equity = broker.equity()
    if sink is not None:
        sink.send(f"AIMOS paper run done: {summary.decisions} decisions, "
                  f"{summary.trades_opened} trades, equity {summary.final_equity:.2f}")
        summary.telegram_messages = sink.sent
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="AIMOS paper trader.")
    p.add_argument("--offline", action="store_true", help="synthetic data, no network/keys")
    p.add_argument("--ticks", type=int, default=None, help="stop after N ticks (0 = forever)")
    args = p.parse_args(argv)
    offline = True if args.offline else None
    summary = asyncio.run(run_paper(offline=offline, max_ticks=args.ticks))
    print(f"paper run: ticks={summary.ticks} decisions={summary.decisions} "
          f"trades={summary.trades_opened} no_trade={summary.no_trades} "
          f"equity={summary.final_equity:.2f}")
    if summary.telegram_messages:
        print(f"telegram messages queued: {len(summary.telegram_messages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
