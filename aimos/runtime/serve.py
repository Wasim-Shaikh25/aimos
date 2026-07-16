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
from aimos.data.live_source import (
    CcxtPublicSource,
    SyntheticSource,
    base_of,
    live_venue_snapshot,
    synthetic_venue_snapshot,
)
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

    universe = _build_universe(params, live_data)
    holder = {
        "latest": {},          # base -> MarketUnderstanding dict (Markets/Anatomy)
        "evidence": {},        # base -> list[Evidence dict] (Engines screen)
        "equity": [broker.equity()],
        "universe": universe,  # Universe object (matrix/tiers/rejections)
        "chosen": {},          # plugin name -> times chosen (Strategies screen)
        "updated": None,       # ISO timestamp of the last completed tick (live badge)
        "tick": 0,
    }

    async def loop() -> None:
        tf = paper["timeframe"]
        bars = int(paper["history_bars"])
        refresh = int(paper.get("universe_refresh_ticks", 60))
        while True:
            try:
                if refresh > 0 and holder["tick"] > 0 and holder["tick"] % refresh == 0:
                    holder["universe"] = _build_universe(params, live_data)
                symbols = _loop_symbols(holder["universe"], paper)
                btc = source.fetch("BTC/USDT", tf, bars)
                for symbol in symbols:
                    df = source.fetch(symbol, tf, bars)
                    if df.empty:
                        continue
                    now = df.index[-1].to_pydatetime().astimezone(timezone.utc)
                    last = df.iloc[-1]
                    vsnap = _venue_snapshot(features, paper, symbol, float(last["close"]), now, live_data)
                    ctx = build_context(base_of(symbol), now, {Timeframe(tf): df},
                                        peers={"BTC": btc}, venue_snapshot=vsnap)
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
                        holder["chosen"][res.plan.plugin] = holder["chosen"].get(res.plan.plugin, 0) + 1
                    broker.step(base_of(symbol), last.to_dict(), now)
                    holder["latest"][base_of(symbol)] = res.understanding.model_dump(mode="json")
                    holder["evidence"][base_of(symbol)] = [e.model_dump(mode="json") for e in res.evidences]
                holder["equity"].append(broker.equity())
                holder["updated"] = clock.now().isoformat()
                holder["tick"] += 1
                heartbeat.beat()
            except Exception:  # noqa: BLE001 — the loop must never die
                log.exception("serve_loop_error")
            await asyncio.sleep(float(paper["loop_seconds"]))

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(loop())
        log.info("serve_started", live_data=live_data, dashboard=DIST.exists(),
                 universe=holder["universe"].source, symbols=len(holder["universe"].selected))
        yield
        task.cancel()

    state = AppState(
        journal=orch.journal, orchestrator=orch,
        positions_provider=lambda: [p.model_dump(mode="json") for p in broker.positions()],
        equity_provider=lambda: holder["equity"],
        latest_state=holder["latest"], effective_config=params.model_dump(),
        matrix_provider=lambda: _universe_payload(holder["universe"], paper, holder),
        evidence_provider=lambda sym: {"evidences": holder["evidence"].get(base_of(sym), [])},
        strategies_provider=lambda: _strategies_payload(params, holder["chosen"]),
        models_provider=lambda: _models_payload(params, holder["latest"]),
    )
    app = create_app(state)
    app.router.lifespan_context = lifespan
    _mount_dashboard(app)
    return app


def _build_universe(params, live_data: bool):
    """Build the trading universe, or a 2-symbol dev Universe when disabled."""
    from aimos.data.universe_source import Universe, build_universe
    paper = params.paper.model_dump()
    if not paper.get("use_universe", True):
        bases = [base_of(s) for s in paper["symbols"]]
        reg = None
        from aimos.universe.registry import Registry
        from aimos.universe.discovery import MarketInfo
        reg = Registry(primary_exchange=paper["data_exchange"])
        for b in bases:
            reg.add_market(MarketInfo(exchange=paper["data_exchange"], symbol=f"{b}/USDT",
                                      base=b, quote="USDT", type="spot", active=True,
                                      min_notional=5.0, lot_step=0.0, taker_bps=7.5, maker_bps=2.0))
        return Universe(registry=reg, order=bases, selected=bases,
                        symbols=list(paper["symbols"]), source="dev-set",
                        total_discovered=len(bases),
                        tiers={b: "t1" for b in bases})
    return build_universe(paper["data_exchange"], params.universe.model_dump(),
                          live_data=live_data, max_symbols=int(paper.get("max_symbols", 40)))


def _loop_symbols(universe, paper) -> list:
    return universe.symbols if universe.symbols else list(paper["symbols"])


def _universe_payload(universe, paper, holder) -> dict:
    return {
        "matrix": universe.matrix(),
        "tiers": universe.tiers,
        "rejections": universe.rejections,
        "source": universe.source,
        "total_discovered": universe.total_discovered,
        "selected": universe.selected,
        "cross_venues": list(paper.get("cross_venues", [])),
        "cross_venue_bases": sorted(universe.cross_venue_bases(
            int(paper.get("min_venues", 2)) if paper.get("min_venues") else 2)),
        "updated": holder.get("updated"),
    }


def _strategies_payload(params, chosen: dict) -> dict:
    """Every execution plugin: config + how often it was chosen this run (§7)."""
    from aimos.execution.plugins import _CORE
    plugin_cfgs = params.plugins
    rows = []
    for cls, key in _CORE:
        raw = plugin_cfgs.get(key)
        cfg = raw.model_dump() if hasattr(raw, "model_dump") else (raw or {})
        regimes = sorted(r.value for r in getattr(cls, "required_regimes", set())) or ["any"]
        rows.append({
            "name": cls.name, "key": key,
            "enabled": bool(cfg.get("enabled", True)),
            "regimes": regimes,
            "min_confidence": cfg.get("min_confidence", 0),
            "min_coin_health": cfg.get("min_coin_health", 0),
            "chosen": chosen.get(cls.name, 0),
            "config": cfg,
        })
    return {"strategies": rows}


def _models_payload(params, latest: dict) -> dict:
    """The three reasoning models (rule/bayes/ml) + learning/fusion status (§6/§8)."""
    intel = params.intelligence.model_dump()
    learning = params.model_dump().get("learning", {})
    weights = intel.get("fusion_weights", {}) or {}
    votes = {}
    for base, mu in latest.items():
        for eng, p in (mu.get("engine_votes") or {}).items():
            votes.setdefault(eng, []).append(p)
    avg = {k: (sum(v) / len(v) if v else None) for k, v in votes.items()}
    ml_path = intel.get("ml_model_path") or learning.get("ml", {}).get("model_path")
    import os
    ml_loaded = bool(ml_path) and os.path.exists(ml_path)
    return {"models": [
        {"name": "RuleEngine", "kind": "deterministic rules", "fusion_weight": weights.get("rule"),
         "avg_p_up": avg.get("rule"), "status": "active"},
        {"name": "BayesEngine", "kind": "naive-Bayes behavior likelihoods",
         "fusion_weight": weights.get("bayes"), "avg_p_up": avg.get("bayes"), "status": "active"},
        {"name": "MLEngine", "kind": "logistic (learned)", "fusion_weight": weights.get("ml"),
         "avg_p_up": avg.get("ml"),
         "status": "loaded" if ml_loaded else ("shadow (weight 0)" if not weights.get("ml") else "active"),
         "model_path": ml_path, "loaded": ml_loaded},
    ], "fusion_weights": weights, "learning": learning}


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


def _venue_snapshot(features, paper, symbol, mid, now, live_data):
    """Cross-exchange top-of-book when enabled (§5.11): live books, else synthetic."""
    if not features.get("cross_exchange_enabled"):
        return None
    venues = list(paper.get("cross_venues", []))
    if len(venues) < 2:
        return None
    if live_data:
        return live_venue_snapshot(symbol, now, venues)
    return synthetic_venue_snapshot(symbol, mid, now, venues)


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
