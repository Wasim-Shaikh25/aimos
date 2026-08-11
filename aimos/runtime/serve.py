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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from aimos.api.server import AppState, create_app
from aimos.backtest import costs as cost_mod
from aimos.core.clock import LiveClock

from aimos.core.schemas import Action, CapacityCaps, ExecContext, Timeframe, VenueTop
from aimos.data.context import build_context
from aimos.data.live_source import (
    CcxtPublicSource,
    SyntheticSource,
    base_of,
    venue_snapshot_for,
)
from aimos.data.stream_feed import StreamFeed
from aimos.data.streaming import BinanceWebsocketSource, StreamRecorder
from aimos.execution.broker.live import LiveBroker, MandateGate
from aimos.execution.broker.live_router import MultiVenueLiveRouter
from aimos.execution.broker.paper import PaperBroker
from aimos.execution.position_sizer import SizingInputs
from aimos.journal.backup import backup_journal
from aimos.journal.journal import Journal
from aimos.runtime.state_store import ControlStore, RuntimeStateStore, build_snapshot
from aimos.saas.auth_service import FailedLoginTracker
from aimos.saas.config_tenant import load_params_for_org
from aimos.saas.journal_tenant import tenant_journal_path
from aimos.saas.settings import get_saas_config
from aimos.saas.settings_store import SettingsStore
from aimos.telegram.sink import TelegramSink
from aimos.execution.risk_manager import RiskState
from aimos.runtime.pipeline import PipelineOrchestrator
from aimos.runtime.watchdog import Heartbeat
from aimos.risk.analytics_runner import compute_risk_report


try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:  # pragma: no cover - apscheduler is a runtime optional dep
    AsyncIOScheduler = None

log = structlog.get_logger(__name__)
DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"

_PROCESS_MODES = ("combined", "api", "loop")


def _process_mode() -> str:
    """How this process participates in the runtime.

    * ``combined`` (default) — API + trading loop in one process (legacy/dev).
    * ``api``                — API only; state is rehydrated from RuntimeStateStore.
    * ``loop``               — trading loop only; no HTTP server.
    """
    return os.environ.get("AIMOS_PROCESS", "combined").lower().strip() or "combined"


def _apply_controls(components: dict[str, Any], controls: dict[str, Any]) -> None:
    """Apply operator controls from the cross-process control channel."""
    if not controls:
        return
    orch = components["orch"]
    params = components["params"]
    _rebuild_orch = components["_rebuild_orch"]
    if controls.get("halted") and not orch.state.halted:
        orch.halt()
    if not controls.get("halted") and orch.state.halted:
        orch.unhalt()
    if controls.get("global_pause") and not orch.state.global_pause:
        orch.pause()
    if not controls.get("global_pause") and orch.state.global_pause:
        orch.resume()
    if "paused_assets" in controls:
        orch.state.paused_assets = set(controls["paused_assets"])
    if "features" in controls:
        current = params.features.model_dump()
        if current != controls["features"]:
            params.features = params.features.__class__(**controls["features"])
            _rebuild_orch()


def _rehydrate_from_snapshot(components: dict[str, Any],
                             snapshot: dict[str, Any],
                             controls: dict[str, Any]) -> None:
    """Reload a saved runtime snapshot into the local API process objects."""
    if not snapshot and not controls:
        return
    holder = components["holder"]
    if snapshot.get("broker"):
        try:
            components["broker"].load_state(snapshot["broker"])
        except Exception:  # noqa: BLE001
            log.exception("broker_rehydrate_failed")
    if snapshot.get("sim"):
        try:
            components["sim"].load_state(snapshot["sim"])
        except Exception:  # noqa: BLE001
            log.exception("sim_rehydrate_failed")
    if snapshot.get("equity"):
        holder["equity"] = snapshot["equity"]
    view = snapshot.get("view", {})
    if view:
        for key in ("latest", "evidence", "venue_state", "prices", "candles_view",
                    "monitor", "risk_report", "connections", "chosen"):
            if key in view:
                holder.setdefault(key, {}).clear()
                holder[key].update(view[key])
        if "matrix" in view:
            holder.setdefault("matrix_view", {}).clear()
            holder["matrix_view"].update(view["matrix"])
        holder["updated"] = view.get("updated")
        holder["tick"] = view.get("tick", holder["tick"])
    _apply_controls(components, controls)


def _build_view(holder: dict[str, Any], connections: dict[str, Any],
                params: Any, paper: dict[str, Any]) -> dict[str, Any]:
    """Serializable view of the loop state for the API process (REQ-13)."""
    candles_view = {
        base: _candles_payload(holder, base)
        for base in holder.get("candles", {})
    }
    return {
        "latest": dict(holder.get("latest", {})),
        "evidence": dict(holder.get("evidence", {})),
        "venue_state": dict(holder.get("venue_state", {})),
        "prices": dict(holder.get("prices", {})),
        "candles_view": dict(candles_view),
        "matrix": _universe_payload(holder["universe"], paper, holder),
        "connections": {
            "venues": list(connections.values()),
            "any_live": any(c.get("connected") for c in connections.values()),
        },
        "risk_report": dict(holder.get("risk_report", {})),
        "monitor": dict(holder.get("monitor", {})),
        "updated": holder.get("updated"),
        "tick": holder.get("tick", 0),
        "chosen": dict(holder.get("chosen", {})),
    }


def _build_components(offline: Optional[bool] = None) -> dict[str, Any]:
    """Construct the shared runtime components used by the API, the loop, or both."""
    Path("state").mkdir(exist_ok=True)
    clock = LiveClock()
    org_id = os.environ.get("AIMOS_RUNTIME_ORG_ID", "local")
    params = load_params_for_org(org_id)
    features = params.features.model_dump()
    paper = params.paper.model_dump()
    costs_cfg = params.costs.model_dump()
    primary_venue = paper["data_exchange"]
    live_data = features["live_data"] if offline is None else (not offline)
    health_cfg = params.model_dump().get("health", {}) or {}
    storage_cfg = params.model_dump().get("storage", {}) or {}
    database_url = storage_cfg.get("database_url", "") or ""
    jpath = database_url or tenant_journal_path(org_id, params)
    state_dir: Optional[Path] = Path("state") / "tenants" / org_id
    if not database_url and jpath != ":memory:":
        state_dir = Path(jpath).parent / f"tenant_{org_id}_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_store = RuntimeStateStore(org_id, state_dir=state_dir, database_url=database_url)
    control_store = ControlStore(org_id, state_dir=state_dir, database_url=database_url)
    saved_state = state_store.load()
    controls = control_store.load()
    halt_file = str(state_dir / "RUNTIME_HALT")
    orch = PipelineOrchestrator(params, clock=clock, journal=Journal(jpath, org_id=org_id), halt_file=halt_file)
    broker = PaperBroker(float(paper["starting_equity_usdt"]), cost_mod.from_config(costs_cfg),
                         venue=paper["data_exchange"])
    heartbeat = Heartbeat("state/heartbeat", clock=clock)

    def _readyz_payload() -> dict:
        stale_after = float(health_cfg.get("heartbeat_stale_seconds", 30))
        last = heartbeat.last_beat()
        age = float("inf") if last is None else (clock.now() - last).total_seconds()
        journal_writable = orch.journal.is_writable()
        ready = journal_writable and age < stale_after
        return {
            "status": "ok" if ready else "not ready",
            "ready": ready,
            "journal_writable": journal_writable,
            "heartbeat_age_seconds": age if last is not None else None,
            "heartbeat_stale_seconds": stale_after,
        }

    caps = _caps(params)
    sources: dict = {}
    streaming_cfg = params.model_dump().get("streaming", {})
    stream_feed = StreamFeed(
        book_window_minutes=float(streaming_cfg.get("book_window_minutes", 1.0)),
        trade_window_minutes=float(streaming_cfg.get("trade_window_minutes", 5.0)),
        min_notional_usd=float(streaming_cfg.get("min_notional_usd", 100.0)),
        max_recent_trades=int(streaming_cfg.get("max_recent_trades", 1000)),
    )

    def src(venue: str):
        if venue not in sources:
            sources[venue] = _make_source(live_data, venue, seed_salt=_venue_seed(venue))
        return sources[venue]

    sink = None
    if features.get("telegram_enabled"):
        sink = TelegramSink()
        sink.attach(orch.bus)
        sink.send("🤖 AIMOS paper server started — analyzing the universe.")
    status_every = int(paper.get("telegram_status_ticks", 0))

    universe = _build_universe(params, live_data)
    from aimos.execution.broker.multivenue import MultiVenueSim
    analysis_venues = sorted({v for row in universe.matrix().values() for v in row}) \
        or [paper["data_exchange"]]
    sim = MultiVenueSim(venues=analysis_venues,
                        start_usdt_total=float(paper["starting_equity_usdt"]),
                        taker_bps=float(costs_cfg["taker_bps"]))
    connections = _run_preflight(params, analysis_venues)
    holder = {
        "latest": {},
        "evidence": {},
        "venue_state": {},
        "prices": {},
        "candles": {},
        "candles_view": {},
        "equity": [broker.equity()],
        "universe": universe,
        "chosen": {},
        "updated": None,
        "tick": 0,
        "features": features,
        "monitor": {},
        "risk_report": {},
        "matrix_view": {},
        "connections": {},
    }

    if saved_state:
        try:
            broker.load_state(saved_state.get("broker", {}))
            sim.load_state(saved_state.get("sim", {}))
            if saved_state.get("equity"):
                holder["equity"] = saved_state["equity"]
        except Exception:  # noqa: BLE001
            log.exception("state_restore_failed")

    def _rebuild_orch() -> None:
        from aimos.execution.decide import ExecutionLayer
        from aimos.observation.runner import build_engines
        orch.obs_engines = build_engines(params, clock)
        orch.execution = ExecutionLayer(params)
        holder["features"] = params.features.model_dump()
        log.info("features_rebuilt", scalp=holder["features"].get("scalp_enabled"),
                 cross_exchange=holder["features"].get("cross_exchange_enabled"))

    from aimos.runtime.features import FeatureController
    feature_ctl = FeatureController(params, _rebuild_orch)

    from aimos.runtime.golive import GoLiveLadder, guard_live_boot
    ladder = GoLiveLadder(journal=orch.journal)
    guard_live_boot(params, ladder)
    live_router = _build_live_router(params, ladder, analysis_venues)

    from aimos.storage.timescale import TimescaleStore
    ts_dsn = storage_cfg.get("timescale_dsn") or database_url
    ts_store = TimescaleStore(ts_dsn)

    from aimos.runtime.monitor_agent import FeatureMonitorAgent
    mon_cfg = params.model_dump().get("monitor", {}) or {}
    monitor = FeatureMonitorAgent(
        _build_monitor_probes(holder, orch, broker, sim, connections, ladder),
        feature_ctl=feature_ctl,
        force_coverage=bool(mon_cfg.get("force_coverage", True)),
    )

    asst_cfg = params.model_dump().get("assistant", {}) or {}
    assistant = None
    if asst_cfg.get("enabled"):
        from aimos.runtime.assistant import Assistant
        assistant = Assistant({
            "decisions": lambda limit=40: _assistant_decisions(orch.journal, limit),
            "performance": lambda: _performance_payload(broker, sim, holder["equity"]),
            "models": lambda: _models_payload(params, holder["latest"]),
            "monitor": lambda: holder["monitor"],
            "features": feature_ctl.snapshot,
            "golive": ladder.status,
            "strategies": lambda: _strategies_payload(params, holder["chosen"]),
            "equity": lambda: holder["equity"],
            "graph": lambda did: _decision_graph(orch.journal, did, params),
        }, cfg=asst_cfg)

    return {
        "clock": clock, "org_id": org_id, "params": params, "features": features,
        "paper": paper, "costs_cfg": costs_cfg, "primary_venue": primary_venue,
        "live_data": live_data, "health_cfg": health_cfg, "jpath": jpath,
        "state_dir": state_dir, "state_store": state_store, "saved_state": saved_state,
        "control_store": control_store, "controls": controls, "orch": orch,
        "broker": broker, "heartbeat": heartbeat, "_readyz_payload": _readyz_payload,
        "caps": caps, "sources": sources, "stream_feed": stream_feed, "src": src,
        "sink": sink, "status_every": status_every, "universe": universe, "sim": sim,
        "analysis_venues": analysis_venues, "connections": connections, "holder": holder,
        "_rebuild_orch": _rebuild_orch, "feature_ctl": feature_ctl, "ladder": ladder,
        "live_router": live_router, "ts_store": ts_store, "mon_cfg": mon_cfg,
        "monitor": monitor, "asst_cfg": asst_cfg, "assistant": assistant,
    }


def build_app(offline: Optional[bool] = None):
    mode = _process_mode()
    if mode == "loop":
        return _build_loop_app(offline)
    components = _build_components(offline)
    clock = components["clock"]
    org_id = components["org_id"]
    params = components["params"]
    features = components["features"]
    paper = components["paper"]
    costs_cfg = components["costs_cfg"]
    primary_venue = components["primary_venue"]
    live_data = components["live_data"]
    health_cfg = components["health_cfg"]
    jpath = components["jpath"]
    state_dir = components["state_dir"]
    state_store = components["state_store"]
    saved_state = components["saved_state"]
    control_store = components["control_store"]
    controls = components["controls"]
    orch = components["orch"]
    broker = components["broker"]
    heartbeat = components["heartbeat"]
    _readyz_payload = components["_readyz_payload"]
    caps = components["caps"]
    sources = components["sources"]
    stream_feed = components["stream_feed"]
    src = components["src"]
    sink = components["sink"]
    status_every = components["status_every"]
    universe = components["universe"]
    sim = components["sim"]
    analysis_venues = components["analysis_venues"]
    connections = components["connections"]
    holder = components["holder"]
    _rebuild_orch = components["_rebuild_orch"]
    feature_ctl = components["feature_ctl"]
    ladder = components["ladder"]
    live_router = components["live_router"]
    ts_store = components["ts_store"]
    mon_cfg = components["mon_cfg"]
    monitor = components["monitor"]
    asst_cfg = components["asst_cfg"]
    assistant = components["assistant"]

    async def loop() -> None:
        tf = paper["timeframe"]
        bars = int(paper["history_bars"])
        refresh = int(paper.get("universe_refresh_ticks", 60))
        primary_venue = paper["data_exchange"]
        while True:
            try:
                _apply_controls(components, control_store.load())
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
                    vsnap = _snapshot_from_mids(venue_df, now, holder["features"])
                    # 3) analyze on EVERY venue (primary journaled/traded; others display)
                    per_venue, prices, primary_res = {}, {}, None
                    for v, d in venue_df.items():
                        last = d.iloc[-1]
                        exec_ctx = _exec_ctx(broker, costs_cfg, caps, v)
                        stream_snap = stream_feed.snapshot(base, now) if features.get("streaming_enabled") else {}
                        ctx = build_context(base, now, {Timeframe(tf): d},
                                            peers={"BTC": btc}, venue_snapshot=vsnap,
                                            **stream_snap)
                        depth = float(costs_cfg["volume_proxy_depth_frac"]) * float(last["volume"]) * float(last["close"])
                        sizing = SizingInputs(volume_24h_usd=float(last["volume"]) * float(last["close"]),
                                              book_depth_1pct_usd=depth)
                        risk = RiskState(open_positions=len(broker.positions()))
                        if v == primary:
                            res = primary_res = await orch.tick(ctx, exec_ctx, sizing, risk)
                            if res.plan.action is not Action.NO_TRADE and not res.plan.meta.get("cross_venue"):
                                broker.place(res.plan)  # directional trade on the primary venue
                                holder["chosen"][res.plan.plugin] = holder["chosen"].get(res.plan.plugin, 0) + 1
                            broker.step(base, last.to_dict(), now)
                            holder["latest"][base] = res.understanding.model_dump(mode="json")
                        else:
                            res = orch.analyze(ctx, exec_ctx, sizing, risk)
                        holder["evidence"].setdefault(base, {})[v] = [e.model_dump(mode="json") for e in res.evidences]
                        per_venue[v] = _venue_summary(res)
                        prices[v] = float(last["close"])
                    # 4) cross-venue arb → two-leg execution against per-venue balances (§4)
                    _maybe_arb(sim, primary_res, base, prices, now, paper, holder,
                               live_router=live_router)
                    holder["venue_state"][base] = per_venue
                    holder["prices"][base] = _price_row(prices)
                    holder["candles"][base] = {v: d for v, d in venue_df.items()}
                    if primary_res is not None:  # time-series (optional TimescaleDB)
                        mu = primary_res.understanding
                        ts_store.write_decision(now, base, primary, mu.regime.value,
                                                mu.p_up, primary_res.plan.action.value,
                                                primary_res.plan.plugin)
                holder["equity"].append(broker.equity() + sim.realized_arb)
                ts_store.write_equity(clock.now(), broker.equity() + sim.realized_arb)
                holder["updated"] = clock.now().isoformat()
                holder["tick"] += 1
                heartbeat.beat()
                view = _build_view(holder, connections, params, paper)
                controls = control_store.load()
                try:
                    await asyncio.to_thread(state_store.save,
                                            build_snapshot(holder, broker, sim, ladder,
                                                           view=view, controls=controls))
                except Exception:  # noqa: BLE001 — persistence must not kill the loop
                    log.exception("state_save_failed")
                if sink and status_every > 0 and holder["tick"] % status_every == 0:
                    n = orch.journal.decision_count()
                    sink.send(f"📊 AIMOS status: {holder['tick']} ticks, {n} decisions, "
                              f"{len(broker.positions())} open, equity {broker.equity():.0f} USDT")
            except Exception:  # noqa: BLE001 — the loop must never die
                log.exception("serve_loop_error")
            await asyncio.sleep(float(paper["loop_seconds"]))

    def _compute_risk_report() -> dict:
        """Compute the VaR/ES + alpha/beta + factor-decomposition report."""
        try:
            report = compute_risk_report(
                equity=holder["equity"],
                params=params,
                data_source=src(primary_venue).fetch,
                universe=holder["universe"],
                clock=clock,
            )
            holder["risk_report"] = report
            log.info("risk_analytics_updated", sample_size=report.get("sample_size"))
            return report
        except Exception:  # noqa: BLE001 — analytics must never kill the loop
            log.exception("risk_analytics_error")
            return holder.get("risk_report", {})

    async def _risk_job() -> None:
        """APScheduler wrapper that runs the heavy analytics off the event loop."""
        await asyncio.to_thread(_compute_risk_report)

    def _backup_job() -> None:
        """Verified journal backup running off the event loop (REQ-12)."""
        try:
            backup_cfg = params.model_dump().get("backup", {}) or {}
            if not bool(backup_cfg.get("enabled", True)):
                return
            if "://" in str(jpath):
                log.info("journal_backup_skipped_database", journal=str(jpath))
                return
            out = backup_journal(
                src=str(jpath),
                dest_dir=str(backup_cfg.get("dest", "backups")),
                keep=int(backup_cfg.get("keep", 14)),
            )
            log.info("journal_backup_ok", path=str(out))
        except FileNotFoundError:
            # Journal may not exist yet on first boot; the next interval will retry.
            log.warning("journal_backup_skipped_no_journal")
        except Exception:  # noqa: BLE001 — backup must never kill the loop
            log.exception("journal_backup_error")

    async def monitor_loop() -> None:
        """Run the feature monitor on an interval: force safe coverage, probe every
        feature, publish the report to /api/monitor and ``state/monitor_report.json``."""
        import json as _json
        if not mon_cfg.get("enabled", False):
            return
        interval = float(mon_cfg.get("interval_seconds", 20))
        report_path = Path("state") / "monitor_report.json"
        log.info("monitor_started", interval=interval, force=monitor.force_coverage_flag)
        while True:
            try:
                monitor.force_coverage()  # enable cross_exchange + scalp once (safe)
                report = monitor.run_once()
                holder["monitor"] = report
                report_path.write_text(_json.dumps(report, indent=2), encoding="utf-8")
                if report["summary"].get("failing"):
                    log.warning("monitor_failing", **report["summary"])
            except Exception:  # noqa: BLE001 — the monitor must never kill the process
                log.exception("monitor_loop_error")
            await asyncio.sleep(interval)

    async def telegram_inbound() -> None:
        """Poll Telegram for commands (/enable, /pause, /status …) in this process."""
        bot = _build_telegram_bot(holder["features"], orch, broker, feature_ctl, clock, assistant)
        if bot is None:
            return
        log.info("telegram_inbound_started")
        while True:
            try:
                await asyncio.to_thread(bot.poll_once)
            except Exception:  # noqa: BLE001 — network hiccup shouldn't kill the poller
                log.exception("telegram_inbound_error")
            await asyncio.sleep(3.0)

    async def stream_loop() -> None:
        """Optional websocket feed: records top-of-book, trades, and tickers to
        ``state/streams/`` for replay and feeds normalized book/trade snapshots
        into the slow paper loop when ``streaming_enabled`` is true."""
        if not features.get("streaming_enabled"):
            return
        symbols = holder["universe"].symbols or list(paper.get("symbols", []))
        if not symbols:
            return
        # Keep only the primary venue mapping; Binance spot is the default feed.
        source = BinanceWebsocketSource(
            symbols=symbols,
            venue="binance",
            recorder=StreamRecorder("state/streams"),
            feed=stream_feed,
        )
        log.info("stream_started", venue=source.venue, symbols=len(symbols))
        await source.run()

    async def _api_state_loader() -> None:
        """API-only process: rehydrate local objects from the loop's snapshot."""
        refresh = float(paper.get("api_state_refresh_seconds", 1.0))
        while True:
            await asyncio.sleep(refresh)
            try:
                snapshot = state_store.load()
                controls = control_store.load()
                _rehydrate_from_snapshot(components, snapshot, controls)
                heartbeat.beat()
                log.debug("api_state_rehydrated", tick=components["holder"].get("tick"))
            except Exception:  # noqa: BLE001
                log.exception("api_state_loader_error")

    @asynccontextmanager
    async def lifespan(app):
        tasks = []
        if mode == "api":
            tasks.append(asyncio.create_task(_api_state_loader()))
        else:
            tasks.append(asyncio.create_task(loop()))
            tasks.append(asyncio.create_task(telegram_inbound()))
            tasks.append(asyncio.create_task(monitor_loop()))
            tasks.append(asyncio.create_task(stream_loop()))

        scheduler = None
        if mode != "api" and AsyncIOScheduler is not None:
            risk_cfg = params.model_dump().get("risk", {}) or {}
            if bool(risk_cfg.get("enabled", True)):
                scheduler = AsyncIOScheduler()
                scheduler.add_job(
                    _risk_job, "interval",
                    seconds=float(risk_cfg.get("interval_seconds", 86400)),
                    next_run_time=datetime.now(timezone.utc),
                    id="risk_analytics",
                    replace_existing=True,
                )
                scheduler.start()
                log.info("risk_analytics_scheduler_started",
                         interval_seconds=float(risk_cfg.get("interval_seconds", 86400)))

                backup_cfg = params.model_dump().get("backup", {}) or {}
                if bool(backup_cfg.get("enabled", True)):
                    scheduler.add_job(
                        _backup_job, "interval",
                        seconds=float(backup_cfg.get("interval_seconds", 3600)),
                        next_run_time=datetime.now(timezone.utc),
                        id="journal_backup",
                        replace_existing=True,
                    )
                    log.info("journal_backup_scheduler_started",
                             interval_seconds=float(backup_cfg.get("interval_seconds", 3600)))

        log.info("serve_started", mode=mode, live_data=live_data, dashboard=DIST.exists(),
                 universe=holder["universe"].source, symbols=len(holder["universe"].selected))
        yield
        for task in tasks:
            task.cancel()
        if scheduler is not None:
            scheduler.shutdown()
        ts_store.close()

    def _feature_setter(name: str, enabled: bool) -> dict:
        result = feature_ctl.set(name, enabled)
        controls = control_store.load()
        controls["features"] = params.features.model_dump()
        control_store.save(controls)
        return result

    if mode == "loop":
        async def _run_forever() -> None:
            async with lifespan(None):
                await asyncio.Event().wait()
        asyncio.run(_run_forever())
        return None

    state = AppState(
        journal=orch.journal, orchestrator=orch, control_store=control_store,
        positions_provider=lambda: [p.model_dump(mode="json") for p in broker.positions()],
        equity_provider=lambda: holder["equity"],
        latest_state=holder["latest"], effective_config=params.model_dump(),
        matrix_provider=lambda: holder.get("matrix_view") or _universe_payload(holder["universe"], paper, holder),
        evidence_provider=lambda sym, venue=None: {
            "evidences": _pick_evidence(holder["evidence"].get(base_of(sym), {}), venue),
            "venues": sorted(holder["evidence"].get(base_of(sym), {})),
        },
        strategies_provider=lambda: _strategies_payload(params, holder["chosen"]),
        models_provider=lambda: _models_payload(params, holder["latest"]),
        prices_provider=lambda: _prices_payload(holder),
        candles_provider=lambda sym: _candles_payload(holder, base_of(sym)),
        venue_state_provider=lambda sym: holder["venue_state"].get(base_of(sym), {}),
        trades_provider=lambda: _trades_payload(broker, sim),
        balances_provider=lambda: _balances_payload(broker, sim, holder.get("connections", connections)),
        connections_provider=lambda: {"venues": list(holder.get("connections", connections).values()),
                                      "any_live": any(c.get("connected") for c in holder.get("connections", connections).values())},
        performance_provider=lambda: _performance_payload(broker, sim, holder["equity"]),
        graph_provider=lambda did: _decision_graph(orch.journal, did, params),
        features_provider=lambda: {**feature_ctl.snapshot(),
                                   "halted": orch.state.halted if orch else False},
        feature_setter=_feature_setter,
        golive_provider=ladder.status,
        golive_setter=lambda gate, passed: ladder.mark(gate) if passed else ladder.unmark(gate),
        monitor_provider=lambda: holder["monitor"] or {"features": [], "summary": {}, "coverage_pct": 0.0,
                                                       "note": "monitor disabled — set monitor.enabled: true"},
        risk_provider=lambda: holder.get("risk_report", {}),
        risk_analyzer=_compute_risk_report,
        health_provider=_readyz_payload,
        assistant=assistant,
    )
    # Wire failed-login alerts to Telegram (REQ-7).  Uses the same sink as the
    # runtime; tests use the default no-op alert_fn.
    saas_cfg = get_saas_config()
    state.auth_alert_tracker = FailedLoginTracker(
        threshold=saas_cfg.failed_login_alert_threshold,
        window_seconds=saas_cfg.failed_login_alert_window_seconds,
        alert_fn=sink.send if sink is not None else None,
    )
    app = create_app(state)
    app.router.lifespan_context = lifespan
    _mount_dashboard(app)
    return app


def _assistant_decisions(journal, limit: int = 40) -> list:
    """Compact recent decisions for the analyst grounding (read-only, no secrets)."""
    import json as _json
    limit = max(1, min(int(limit), 500))
    rows = journal.conn.execute(
        'SELECT decision_id, symbol, "timestamp", payload FROM decisions ORDER BY seq DESC LIMIT ?',
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        rec = _json.loads(r["payload"])
        mu = rec.get("understanding", {}) or {}
        ch = rec.get("chosen", {}) or {}
        out.append({
            "decision_id": r["decision_id"], "timestamp": r["timestamp"], "symbol": r["symbol"],
            "regime": mu.get("regime"), "action": ch.get("action"), "plugin": ch.get("plugin"),
            "p_up": mu.get("p_up"), "confidence": mu.get("confidence"),
            "reasons": (mu.get("reasons") or [])[:3],
        })
    return out


def _build_telegram_bot(features, orch, broker, feature_ctl, clock, assistant=None):
    """Inbound Telegram command bot for this process, or None when not usable."""
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not (features.get("telegram_enabled") and token):
        return None
    try:
        from aimos.telegram.bot import CommandRouter, HttpTransport, TelegramBot
        from aimos.telegram.security import ChatWhitelist, NonceStore
        ids = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",") if x.strip()}
        router = CommandRouter(
            ChatWhitelist(ids), NonceStore(clock), orchestrator=orch, journal=orch.journal,
            positions_provider=lambda: [p.model_dump(mode="json") for p in broker.positions()],
            feature_controller=feature_ctl, assistant=assistant,
        )
        return TelegramBot(HttpTransport(token), router)
    except Exception:  # noqa: BLE001
        log.exception("telegram_inbound_build_failed")
        return None


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
    feats = params.features.model_dump()
    if feats.get("scalp_enabled"):  # §17 — appended dynamically in build_plugins
        scfg = params.scalp.model_dump() if hasattr(params.scalp, "model_dump") else {}
        rows.append({
            "name": "MomentumScalp", "key": "scalp", "enabled": True,
            "regimes": scfg.get("context_gate", {}).get("allowed_regimes", ["any"]),
            "min_confidence": scfg.get("context_gate", {}).get("min_confidence", 0),
            "min_coin_health": 0, "chosen": chosen.get("MomentumScalp", 0), "config": scfg,
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
        return {v: perturb_for_venue(base, v, salt=symbol) for v in venues}
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


def _decision_graph(journal, decision_id: str, params) -> dict:
    """Node/edge mind-map of one journaled decision (§5.3): engines → fusion →
    regime → eligible strategies → chosen. Built purely from the journal record."""
    import json as _json
    from aimos.execution.plugins import _CORE
    row = journal.conn.execute(
        "SELECT payload FROM decisions WHERE decision_id = ? LIMIT 1", (decision_id,)
    ).fetchone()
    if row is None:
        return {"nodes": [], "edges": []}
    rec = _json.loads(row["payload"])
    mu, chosen = rec["understanding"], rec["chosen"]
    nodes, edges = [], []

    def node(nid, layer, label, sub="", kind="", highlight=False):
        nodes.append({"id": nid, "layer": layer, "label": str(label), "sub": sub,
                      "kind": kind, "highlight": highlight})

    votes = mu.get("engine_votes", {})
    for eng in ("rule", "bayes", "ml"):
        node(f"eng_{eng}", 0, eng.upper(), f"p_up {float(votes.get(eng, 0.0)):.2f}", "engine")
        edges.append({"from": f"eng_{eng}", "to": "fusion"})
    node("fusion", 1, "Fusion", f"p_up {float(mu['p_up']):.2f} · conf {float(mu['confidence']) * 100:.0f}%", "fusion")
    edges.append({"from": "fusion", "to": "regime"})
    node("regime", 2, mu["regime"], f"{mu.get('behavior', '')} · bias {mu.get('direction_bias', '')}", "regime")

    reg = mu["regime"]
    chosen_plugin = chosen.get("plugin")
    plugin_cfgs = params.plugins
    for cls, key in _CORE:
        raw = plugin_cfgs.get(key)
        cfg = raw.model_dump() if hasattr(raw, "model_dump") else (raw or {})
        if not cfg.get("enabled", True):
            continue
        regimes = {r.value for r in getattr(cls, "required_regimes", set())}
        if regimes and reg not in regimes:
            continue  # not eligible in this regime
        hl = cls.name == chosen_plugin
        node(f"strat_{key}", 3, cls.name, "✓ chosen" if hl else "eligible", "strategy", hl)
        edges.append({"from": "regime", "to": f"strat_{key}"})
        edges.append({"from": f"strat_{key}", "to": "decision"})

    if params.features.model_dump().get("scalp_enabled"):  # §17
        allowed = params.scalp.model_dump().get("context_gate", {}).get("allowed_regimes", [])
        if reg in allowed:
            hl = chosen_plugin == "MomentumScalp"
            node("strat_scalp", 3, "MomentumScalp", "✓ chosen" if hl else "eligible", "strategy", hl)
            edges.append({"from": "regime", "to": "strat_scalp"})
            edges.append({"from": "strat_scalp", "to": "decision"})

    action = chosen.get("action", "no_trade")
    score = chosen.get("score")
    sub = f"{chosen_plugin}" + (f" · score {float(score):.2f}" if score is not None else "")
    node("decision", 4, action, sub, "decision", True)
    return {"nodes": nodes, "edges": edges, "symbol": rec.get("symbol"),
            "reasons": mu.get("reasons", []), "decision_id": decision_id}


def _maybe_arb(sim, primary_res, base, prices, now, paper, holder,
               live_router: Optional[MultiVenueLiveRouter] = None) -> None:
    """Execute a chosen cross-venue arb as two simulated legs (buy cheap/sell rich).

    When ``live_router`` is provided (mandate enabled + go-live ladder complete +
    per-venue API keys present), the legs are routed through :class:`LiveBroker` so
    they can be placed on real exchanges.  Otherwise the paper/sim ledger is used.
    """
    if primary_res is None or primary_res.plan.action is Action.NO_TRADE:
        return
    m = primary_res.plan.meta
    if not m.get("cross_venue"):
        return
    bv, sv = m.get("buy_venue"), m.get("sell_venue")
    if bv not in prices or sv not in prices:
        return
    notional = float(primary_res.plan.size_quote or 0.0) or float(paper["starting_equity_usdt"]) * 0.01
    if live_router is not None and live_router.brokers:
        live_router.execute_arb(
            base_symbol=f"{base}/USDT", buy_venue=bv, sell_venue=sv,
            notional_usd=notional,
            buy_price=prices[bv], sell_price=prices[sv],
            total_notional_after=notional,
            positions_after=len(sim.trades) + 1,
        )
        holder["chosen"]["CrossExchangeArb"] = holder["chosen"].get("CrossExchangeArb", 0) + 1
        return
    sim.execute_arb(base, bv, sv, prices[bv], prices[sv], notional, now)
    holder["chosen"]["CrossExchangeArb"] = holder["chosen"].get("CrossExchangeArb", 0) + 1


def _build_live_router(params, ladder, venues: list[str]) -> Optional[MultiVenueLiveRouter]:
    """Build a :class:`MultiVenueLiveRouter` only when every fail-closed gate is open.

    Returns ``None`` unless:
      - ``features.multi_venue_live`` is true
      - ``mode`` is ``live`` or ``mandate.enabled`` is true
      - the go-live ladder is complete
      - per-venue API credentials are stored via the Settings UI
    """
    features = params.features.model_dump()
    if not features.get("multi_venue_live"):
        return None
    pd = params.model_dump()
    mandate_cfg = pd.get("mandate", {})
    if not mandate_cfg.get("enabled") and str(pd.get("mode", "paper")).lower() != "live":
        return None
    if not ladder.live_allowed():
        return None

    store = SettingsStore("default")
    if len(venues) < 2:
        return None

    mandate = MandateGate(mandate_cfg)
    brokers: dict[str, LiveBroker] = {}
    for venue in venues:
        creds = store.get_exchange_credentials(venue)
        if not creds or not creds.get("apiKey"):
            continue
        exchange_id = creds.get("exchange_id", venue)
        perms = {"withdraw": bool(creds.get("withdraw", False))}
        try:
            brokers[venue] = LiveBroker(
                exchange_id=exchange_id,
                mandate=mandate,
                api_permissions=perms,
                api_credentials=creds,
                testnet=bool(creds.get("testnet", True)),
            )
        except PermissionError:
            continue
    if len(brokers) < 2:
        return None
    return MultiVenueLiveRouter(brokers)


def _build_monitor_probes(holder, orch, broker, sim, connections, ladder) -> dict:
    """One probe per feature for the monitor agent. Each reads live state and
    returns ok / degraded / failing — degraded means "wired but not yet exercised"
    (normal early in a run), failing means "should have data and doesn't"."""
    from aimos.runtime.monitor_agent import degraded, failing, ok

    def universe():
        u = holder["universe"]
        n = len(u.selected)
        return ok("universe", f"{n} symbols ({u.source})") if n else failing("universe", "empty universe")

    def prices():
        rows = holder["prices"]
        multi = [b for b, r in rows.items() if len(r.get("venues", {})) >= 2]
        if not rows:
            return degraded("prices", "no ticks yet")
        return ok("prices", f"{len(rows)} coins, {len(multi)} multi-venue")

    def decisions():
        n = orch.journal.decision_count()
        return ok("decisions", f"{n} journaled") if n else degraded("decisions", "no ticks yet")

    def per_venue():
        vs = holder["venue_state"]
        venues = {v for row in vs.values() for v in row}
        return ok("per_venue_analysis", f"{len(vs)} coins × {len(venues)} venues") if vs \
            else degraded("per_venue_analysis", "no ticks yet")

    def engines():
        ev = holder["evidence"]
        n_ev = sum(len(vv) for by in ev.values() for vv in by.values())
        return ok("engines", f"{n_ev} evidences across {len(ev)} coins") if n_ev \
            else degraded("engines", "no ticks yet")

    def cross_exchange():
        if not holder["features"].get("cross_exchange_enabled"):
            return degraded("cross_exchange", "flag off (force_coverage will enable)")
        disl = [r["dislocation_bps"] for r in holder["prices"].values() if "dislocation_bps" in r]
        arb = len(sim.trades)
        if arb:
            return ok("cross_exchange", f"{arb} arb legs executed")
        if disl:
            return ok("cross_exchange", f"dislocation seen (max {max(disl):.1f} bps), awaiting threshold")
        return degraded("cross_exchange", "enabled, no dislocation computed yet")

    def scalp():
        if not holder["features"].get("scalp_enabled"):
            return degraded("scalp", "flag off")
        chosen = holder["chosen"].get("MomentumScalp", 0)
        return ok("scalp", f"chosen {chosen}×" if chosen else "enabled, not yet chosen")

    def trades():
        n = len(broker.trade_history()) + len(sim.trades)
        return ok("trades", f"{n} trades") if n else degraded("trades", "no fills yet")

    def balances():
        rows = sim.balances_rows()
        return ok("balances", f"{len(rows)} venues, ${sim.total_usdt():.0f}") if rows \
            else failing("balances", "no balance sheet")

    def performance():
        eq = holder["equity"]
        return ok("performance", f"{len(eq)} equity points") if len(eq) > 1 \
            else degraded("performance", "warming up")

    def mind_map():
        n = orch.journal.decision_count()
        return ok("mind_map", "decision graph available") if n else degraded("mind_map", "no decisions yet")

    def connections_probe():
        if not connections:
            return degraded("connections", "no keys configured (keyless mode)")
        live = sum(1 for c in connections.values() if c.get("connected"))
        return ok("connections", f"{live}/{len(connections)} venues connected")

    def go_live():
        st = ladder.status()
        return ok("go_live", f"{st.get('percent', 0)}% gates signed off")

    return {
        "universe": universe, "prices": prices, "decisions": decisions,
        "per_venue_analysis": per_venue, "engines": engines, "cross_exchange": cross_exchange,
        "scalp": scalp, "trades": trades, "balances": balances, "performance": performance,
        "mind_map": mind_map, "connections": connections_probe, "go_live": go_live,
    }


def _trades_payload(broker, sim) -> dict:
    """Directional + arb trades, most recent first (Trade History, §5.5)."""
    trades = broker.trade_history() + list(sim.trades)
    trades.sort(key=lambda t: (t.get("closed_at") or t.get("opened_at") or ""), reverse=True)
    return {"trades": trades[:200], "n_arb": len(sim.trades)}


def _run_preflight(params, venues) -> dict:
    """Phase D read-only self-check: load secrets, verify each venue connects.
    Empty (skipped) when no keys are configured — the safe, keyless default."""
    from aimos.account.preflight import preflight_check
    from aimos.account.secrets import load_secrets
    pd = params.model_dump()
    account = pd.get("account", {}) or {}
    secrets_file = (pd.get("secrets", {}) or {}).get("file", "")
    creds = load_secrets(secrets_file, venues=venues)
    if not creds or not account.get("preflight_on_start", True):
        return {}
    return preflight_check(venues, creds)  # authenticates + fetch_balance, NO orders


def _balances_payload(broker, sim, connections=None) -> dict:
    """Per-venue balances: LIVE (from the read-only preflight) when a venue's key is
    connected, else the simulated sheet. Directional cash on the primary venue (§5.4)."""
    connections = connections or {}
    rows = []
    live_any = False
    sim_rows = {r["venue"]: r for r in sim.balances_rows()}
    for venue in sorted(set(sim_rows) | set(connections)):
        conn = connections.get(venue, {})
        if conn.get("connected"):
            live_any = True
            rows.append({"venue": venue, "usdt": conn.get("usdt_free", 0.0),
                         "assets": {}, "source": "live",
                         "can_trade": conn.get("can_trade", False)})
        else:
            base = sim_rows.get(venue, {"venue": venue, "usdt": 0.0, "assets": {}})
            rows.append({**base, "source": "simulated"})
    total = sum(r["usdt"] for r in rows)
    return {"venues": rows, "total_usdt": total, "directional_cash": broker.cash(),
            "live": live_any,
            "note": ("live balances from read-only keys" if live_any
                     else "simulated — add read-only keys for live balances (Phase D preflight)")}


def _performance_payload(broker, sim, equity) -> dict:
    from aimos.execution.broker.multivenue import performance
    return performance(broker.trade_history(), list(sim.trades), list(equity))


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


def _candles_payload(holder, base: str) -> dict:
    """Return OHLC history for ``base`` across venues (Candlestick chart, §5.1)."""
    cached = holder.get("candles_view", {}).get(base)
    if cached:
        return cached
    venue_dfs = holder.get("candles", {}).get(base, {})
    if not venue_dfs:
        return {"venues": [], "candles": []}
    venues = sorted(venue_dfs)
    out = {}
    for v, df in venue_dfs.items():
        if df is None or df.empty:
            continue
        out[v] = [
            {
                "time": int(ts.timestamp()),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["high"]), 6),
                "low": round(float(row["low"]), 6),
                "close": round(float(row["close"]), 6),
            }
            for ts, row in df.iterrows()
        ]
    return {"venues": venues, "candles": out}


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

    index = DIST / "index.html"
    root = DIST.resolve()

    @app.get("/")
    def _index():  # noqa: ANN202
        return FileResponse(str(index))

    @app.get("/{full_path:path}")
    def _spa(full_path: str):  # noqa: ANN202 — SPA fallback (client-side routes)
        # Serve a real file ONLY when it resolves to a path genuinely inside the
        # built dist tree; otherwise fall back to the SPA shell (client-side route).
        # resolve() normalizes percent-decoded "../" and symlinks so an attacker
        # cannot escape DIST to read state/.jwt_secret, secrets, or arbitrary files.
        try:
            candidate = (root / full_path).resolve()
        except (OSError, ValueError):
            return FileResponse(str(index))
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(str(candidate))
        return FileResponse(str(index))


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


if _process_mode() == "loop":
    app = None
else:
    app = build_app()  # module-level ASGI app for `uvicorn aimos.runtime.serve:app`


def main() -> int:  # pragma: no cover - launches the server
    import uvicorn
    if app is None:
        raise RuntimeError("ASGI app unavailable in AIMOS_PROCESS=loop mode — use aimos.runtime.loop_process")
    # Default to loopback so a bare `python -m aimos.runtime.serve` is never
    # publicly reachable by accident (audit finding H1). Set AIMOS_HOST=0.0.0.0
    # explicitly (behind a VPN/tunnel/proxy) to bind all interfaces.
    host = os.environ.get("AIMOS_HOST", "127.0.0.1")
    port = int(os.environ.get("AIMOS_PORT", "8000"))
    log.info("aimos_serve", url=f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
