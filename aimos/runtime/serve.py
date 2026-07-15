"""Full-stack serve entrypoint — API + built dashboard + background paper loop.

One process serves everything on one port:
* the FastAPI backend (journal-backed reads, CONFIRM-gated controls),
* the built React dashboard (``dashboard/dist`` as static files, if present),
* a background paper-trading loop feeding the same journal the API reads.

    python -m aimos.runtime.serve            # http://0.0.0.0:8000

Offline synthetic data by default (no keys/network). Set
``AIMOS__FEATURES__LIVE_DATA=true`` (and ``pip install '.[data]'``) for live
public candles. Not in the linted layers.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from typing import Optional

import structlog

from aimos.api.server import AppState, create_app
from aimos.backtest import costs as cost_mod
from aimos.core.clock import LiveClock
from aimos.core.config import load_params
from aimos.core.schemas import Action, CapacityCaps, ExecContext, Timeframe
from aimos.data.context import build_context
from aimos.data.live_source import CcxtPublicSource, SyntheticSource, base_of
from aimos.execution.broker.paper import PaperBroker
from aimos.execution.position_sizer import SizingInputs
from aimos.execution.risk_manager import RiskState
from aimos.runtime.pipeline import PipelineOrchestrator
from aimos.runtime.watchdog import Heartbeat

log = structlog.get_logger(__name__)
DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"


def build_app(offline: Optional[bool] = None):
    params = load_params()
    features = params.features.model_dump()
    paper = params.paper.model_dump()
    costs_cfg = params.costs.model_dump()
    live_data = features["live_data"] if offline is None else (not offline)

    Path("state").mkdir(exist_ok=True)
    clock = LiveClock()
    orch = PipelineOrchestrator(params, clock=clock)  # in-memory journal
    broker = PaperBroker(float(paper["starting_equity_usdt"]), cost_mod.from_config(costs_cfg))
    heartbeat = Heartbeat("state/heartbeat", clock=clock)
    caps = _caps(params)
    source = _make_source(live_data, paper["data_exchange"])

    holder = {"latest": {}, "equity": [broker.equity()]}

    async def loop() -> None:
        symbols = list(paper["symbols"])
        tf = paper["timeframe"]
        bars = int(paper["history_bars"])
        while True:
            try:
                btc = source.fetch("BTC/USDT", tf, bars)
                for symbol in symbols:
                    df = source.fetch(symbol, tf, bars)
                    if df.empty:
                        continue
                    now = df.index[-1].to_pydatetime().astimezone(timezone.utc)
                    ctx = build_context(base_of(symbol), now, {Timeframe(tf): df}, peers={"BTC": btc})
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
                    res = await orch.tick(
                        ctx, exec_ctx,
                        SizingInputs(volume_24h_usd=float(last["volume"]) * float(last["close"]),
                                     book_depth_1pct_usd=depth),
                        RiskState(open_positions=len(broker.positions())),
                    )
                    if res.plan.action is not Action.NO_TRADE:
                        broker.place(res.plan)
                    broker.step(base_of(symbol), last.to_dict(), now)
                    holder["latest"][base_of(symbol)] = res.understanding.model_dump(mode="json")
                holder["equity"].append(broker.equity())
                heartbeat.beat()
            except Exception:  # noqa: BLE001 — the loop must never die
                log.exception("serve_loop_error")
            await asyncio.sleep(float(paper["loop_seconds"]))

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(loop())
        log.info("serve_started", live_data=live_data, dashboard=DIST.exists())
        yield
        task.cancel()

    state = AppState(
        journal=orch.journal, orchestrator=orch,
        positions_provider=lambda: [p.model_dump(mode="json") for p in broker.positions()],
        equity_provider=lambda: holder["equity"],
        latest_state=holder["latest"], effective_config=params.model_dump(),
    )
    app = create_app(state)
    app.router.lifespan_context = lifespan
    _mount_dashboard(app)
    return app


def _mount_dashboard(app) -> None:
    if not DIST.exists():
        log.warning("dashboard_not_built", hint="cd dashboard && npm install && npm run build")
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    def _index():  # noqa: ANN202
        return FileResponse(str(DIST / "index.html"))

    @app.get("/{full_path:path}")
    def _spa(full_path: str):  # noqa: ANN202 — SPA fallback (client-side routes)
        f = DIST / full_path
        return FileResponse(str(f if f.is_file() else DIST / "index.html"))


def _make_source(live_data: bool, exchange: str):
    """Live public source when requested + ccxt available, else synthetic."""
    if not live_data:
        return SyntheticSource()
    try:
        import ccxt  # noqa: F401 - availability probe
        return CcxtPublicSource(exchange)
    except Exception:  # noqa: BLE001
        log.warning("ccxt_unavailable_fallback_synthetic", hint="pip install -e '.[data]'")
        return SyntheticSource()


def _caps(params) -> CapacityCaps:
    c = params.capacity.model_dump()
    return CapacityCaps(
        max_equity_pct_per_asset=float(c["max_equity_pct_per_asset"]),
        max_pct_of_24h_volume=float(c["max_pct_of_24h_volume"]),
        max_pct_of_book_depth=float(c["max_pct_of_book_depth"]),
        max_exit_slippage_bps=float(c["max_exit_slippage_bps"]),
        stress_exit_bps=float(c["stress_exit_bps"]),
    )


app = build_app()  # module-level ASGI app for `uvicorn aimos.runtime.serve:app`


def main() -> int:  # pragma: no cover - launches the server
    import uvicorn
    host = os.environ.get("AIMOS_HOST", "0.0.0.0")
    port = int(os.environ.get("AIMOS_PORT", "8000"))
    log.info("aimos_serve", url=f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
