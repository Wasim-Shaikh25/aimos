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
from aimos.core.schemas import Action, CapacityCaps, ExecContext, Timeframe, VenueTop
from aimos.data.context import build_context
from aimos.data.live_source import (
    CcxtPublicSource,
    SyntheticSource,
    base_of,
    venue_snapshot_for,
)
from aimos.execution.broker.paper import PaperBroker
from aimos.execution.position_sizer import SizingInputs
from aimos.journal.journal import Journal
from aimos.telegram.sink import TelegramSink
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
    # persistent journal when paper.journal_path is set (deployments), else in-memory
    jpath = paper.get("journal_path") or ":memory:"
    orch = PipelineOrchestrator(params, clock=clock, journal=Journal(jpath))
    broker = PaperBroker(float(paper["starting_equity_usdt"]), cost_mod.from_config(costs_cfg))
    heartbeat = Heartbeat("state/heartbeat", clock=clock)
    caps = _caps(params)
    sources: dict = {}  # venue -> DataSource (lazy, per-venue)

    def src(venue: str):
        if venue not in sources:
            sources[venue] = _make_source(live_data, venue, seed_salt=_venue_seed(venue))
        return sources[venue]

    # Telegram: same process as the dashboard + loop (one deployable). Dry-run
    # (logs, never sends) when no token, so this is safe with the flag off too.
    sink = None
    if features.get("telegram_enabled"):
        sink = TelegramSink()  # token/allowed-ids from env
        sink.attach(orch.bus)  # → trade-opened / risk-alert messages
        sink.send("🤖 AIMOS paper server started — analyzing the universe.")
    status_every = int(paper.get("telegram_status_ticks", 0))

    universe = _build_universe(params, live_data)
    holder = {
        "latest": {},          # base -> primary-venue MarketUnderstanding (Markets/Anatomy)
        "evidence": {},        # base -> {venue: [Evidence dict]} (Engines screen, per venue)
        "venue_state": {},     # base -> {venue: {regime,p_up,confidence,action,plugin}} (§3.1)
        "prices": {},          # base -> {venues:{v:mid}, dislocation_bps, cheap, rich}
        "equity": [broker.equity()],
        "universe": universe,
        "chosen": {},
        "updated": None,
        "tick": 0,
    }

    async def loop() -> None:
        tf = paper["timeframe"]
        bars = int(paper["history_bars"])
        refresh = int(paper.get("universe_refresh_ticks", 60))
        primary_venue = paper["data_exchange"]
        while True:
            try:
                if refresh > 0 and holder["tick"] > 0 and holder["tick"] % refresh == 0:
                    holder["universe"] = _build_universe(params, live_data)
                registry = holder["universe"].registry
                symbols = _loop_symbols(holder["universe"], paper)
                btc = src(primary_venue).fetch("BTC/USDT", tf, bars)
                for symbol in symbols:
                    base = base_of(symbol)
                    coin_venues = registry.venues(base) or [primary_venue]
                    # 1) per-venue candles: real per venue when live; offline a shared
                    #    walk perturbed a few bps per venue (realistic, §3.1)
                    venue_df = _fetch_venue_candles(src, primary_venue, coin_venues,
                                                    symbol, tf, bars, live_data)
                    if not venue_df:
                        continue
                    primary = primary_venue if primary_venue in venue_df else next(iter(venue_df))
                    now = venue_df[primary].index[-1].to_pydatetime().astimezone(timezone.utc)
                    # 2) cross-venue snapshot from the per-venue mids (for §5.11 engine)
                    vsnap = _snapshot_from_mids(venue_df, now, features)
                    # 3) analyze on EVERY venue (primary journaled/traded; others display)
                    per_venue, prices = {}, {}
                    for v, d in venue_df.items():
                        last = d.iloc[-1]
                        exec_ctx = _exec_ctx(broker, costs_cfg, caps, v)
                        ctx = build_context(base, now, {Timeframe(tf): d},
                                            peers={"BTC": btc}, venue_snapshot=vsnap)
                        depth = float(costs_cfg["volume_proxy_depth_frac"]) * float(last["volume"]) * float(last["close"])
                        sizing = SizingInputs(volume_24h_usd=float(last["volume"]) * float(last["close"]),
                                              book_depth_1pct_usd=depth)
                        risk = RiskState(open_positions=len(broker.positions()))
                        if v == primary:
                            res = await orch.tick(ctx, exec_ctx, sizing, risk)
                            if res.plan.action is not Action.NO_TRADE:
                                broker.place(res.plan)
                                holder["chosen"][res.plan.plugin] = holder["chosen"].get(res.plan.plugin, 0) + 1
                            broker.step(base, last.to_dict(), now)
                            holder["latest"][base] = res.understanding.model_dump(mode="json")
                        else:
                            res = orch.analyze(ctx, exec_ctx, sizing, risk)
                        holder["evidence"].setdefault(base, {})[v] = [e.model_dump(mode="json") for e in res.evidences]
                        per_venue[v] = _venue_summary(res)
                        prices[v] = float(last["close"])
                    holder["venue_state"][base] = per_venue
                    holder["prices"][base] = _price_row(prices)
                holder["equity"].append(broker.equity())
                holder["updated"] = clock.now().isoformat()
                holder["tick"] += 1
                heartbeat.beat()
                if sink and status_every > 0 and holder["tick"] % status_every == 0:
                    n = orch.journal.decision_count()
                    sink.send(f"📊 AIMOS status: {holder['tick']} ticks, {n} decisions, "
                              f"{len(broker.positions())} open, equity {broker.equity():.0f} USDT")
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
        evidence_provider=lambda sym, venue=None: {
            "evidences": _pick_evidence(holder["evidence"].get(base_of(sym), {}), venue),
            "venues": sorted(holder["evidence"].get(base_of(sym), {})),
        },
        strategies_provider=lambda: _strategies_payload(params, holder["chosen"]),
        models_provider=lambda: _models_payload(params, holder["latest"]),
        prices_provider=lambda: _prices_payload(holder),
        venue_state_provider=lambda sym: holder["venue_state"].get(base_of(sym), {}),
    )
    app = create_app(state)
    app.router.lifespan_context = lifespan
    _mount_dashboard(app)
    return app


def _build_universe(params, live_data: bool):
    """Trading universe for the loop (real top-N or dev set) — shared helper."""
    from aimos.data.universe_source import runtime_universe
    return runtime_universe(params, live_data)


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


# -- multi-venue helpers (§3.1, Phase A) -------------------------------------


def _venue_seed(venue: str) -> int:
    return abs(hash(venue)) % 997  # per-venue deterministic offset for synthetic data


def _fetch_venue_candles(src, primary_venue, venues, symbol, tf, bars, live_data):
    """Per-venue OHLCV. Real per-venue candles when a live source is available;
    otherwise (synthetic — offline OR ccxt-absent fallback) one shared walk
    perturbed a few bps per venue, so per-venue prices stay realistically close."""
    from aimos.data.live_source import SyntheticSource, perturb_for_venue
    primary_src = src(primary_venue)
    if isinstance(primary_src, SyntheticSource):
        base = primary_src.fetch(symbol, tf, bars)
        if base.empty:
            return {}
        return {v: perturb_for_venue(base, v) for v in venues}
    out = {}
    for v in venues:
        d = src(v).fetch(symbol, tf, bars)
        if not d.empty:
            out[v] = d
    return out


def _exec_ctx(broker, costs_cfg, caps, venue):
    return ExecContext(
        equity_usdt=broker.equity(), open_positions=broker.positions(),
        portfolio_heat_pct=0.0, fee_taker_bps=float(costs_cfg["taker_bps"]),
        fee_maker_bps=float(costs_cfg["maker_bps"]),
        slippage_entry_bps=float(costs_cfg["slip_base_bps"]),
        slippage_exit_bps=float(costs_cfg["slip_base_bps"]),
        venue=venue, caps=caps,
    )


def _snapshot_from_mids(venue_df, now, features):
    """VenueTop per venue from each venue's last close (feeds the §5.11 engine)."""
    if not features.get("cross_exchange_enabled") or len(venue_df) < 2:
        return None
    from aimos.core.normalize import BPS
    half = float(features.get("venue_spread_bps", 2.0)) / 2.0 / BPS
    snap = {}
    for v, d in venue_df.items():
        mid = float(d.iloc[-1]["close"])
        snap[v] = VenueTop(exchange=v, best_bid=mid * (1 - half), best_ask=mid * (1 + half),
                           mid=mid, timestamp=now)
    return snap


def _venue_summary(res) -> dict:
    mu = res.understanding
    return {"regime": mu.regime.value, "p_up": round(mu.p_up, 4),
            "confidence": round(mu.confidence, 4), "action": res.plan.action.value,
            "plugin": res.plan.plugin}


def _price_row(prices: dict) -> dict:
    """Per-venue mids + max pairwise dislocation (cheap→rich) for the price matrix."""
    from aimos.observation.cross_exchange import compute_dislocation
    row = {"venues": {v: round(m, 4) for v, m in prices.items()}}
    if len(prices) >= 2:
        result = compute_dislocation(prices)
        if result:
            bps, (cheap, rich) = result
            row.update(dislocation_bps=round(bps, 2), cheap=cheap, rich=rich)
    return row


def _pick_evidence(by_venue: dict, venue):
    if not by_venue:
        return []
    if venue and venue in by_venue:
        return by_venue[venue]
    return next(iter(by_venue.values()))  # default: first venue (primary)


def _prices_payload(holder) -> dict:
    rows = []
    for base in sorted(holder["prices"]):
        vstate = holder["venue_state"].get(base, {})
        decisions = {v: {"regime": s["regime"], "action": s["action"], "p_up": s["p_up"]}
                     for v, s in vstate.items()}
        rows.append({"base": base, **holder["prices"][base], "decisions": decisions})
    venues = sorted({v for r in rows for v in r.get("venues", {})})
    return {"venues": venues, "rows": rows, "updated": holder.get("updated")}


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


def _make_source(live_data: bool, exchange: str, seed_salt: int = 0):
    """Live public source per venue when available, else per-venue synthetic.

    ``seed_salt`` makes each venue's synthetic candles differ (so per-venue prices
    and decisions genuinely diverge offline), while staying replay-stable.
    """
    if not live_data:
        return SyntheticSource(seed=seed_salt)
    try:
        import ccxt  # noqa: F401 - availability probe
        return CcxtPublicSource(exchange)
    except Exception:  # noqa: BLE001
        log.warning("ccxt_unavailable_fallback_synthetic", hint="pip install -e '.[data]'")
        return SyntheticSource(seed=seed_salt)


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
