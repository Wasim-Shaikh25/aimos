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
    broker = PaperBroker(float(paper["starting_equity_usdt"]), cost_mod.from_config(costs_cfg),
                         venue=paper["data_exchange"])
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
    # simulated per-venue balances + two-leg arb ledger, seeded across ALL venues
    # the universe spans (not just cross_venues) so arb flows are all accounted (§4)
    from aimos.execution.broker.multivenue import MultiVenueSim
    analysis_venues = sorted({v for row in universe.matrix().values() for v in row}) \
        or [paper["data_exchange"]]
    sim = MultiVenueSim(venues=analysis_venues,
                        start_usdt_total=float(paper["starting_equity_usdt"]),
                        taker_bps=float(costs_cfg["taker_bps"]))
    connections = _run_preflight(params, analysis_venues)  # Phase D read-only self-check
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
        "features": features,  # mutable — the loop reads this so runtime toggles apply
    }

    def _rebuild_orch() -> None:  # after a runtime feature toggle (§ features.py)
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
    guard_live_boot(params, ladder)  # fail-closed: refuse to boot live before the ladder is complete

    from aimos.storage.timescale import TimescaleStore
    ts_store = TimescaleStore(params.model_dump().get("storage", {}).get("timescale_dsn", ""))

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
                    vsnap = _snapshot_from_mids(venue_df, now, holder["features"])
                    # 3) analyze on EVERY venue (primary journaled/traded; others display)
                    per_venue, prices, primary_res = {}, {}, None
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
                    _maybe_arb(sim, primary_res, base, prices, now, paper, holder)
                    holder["venue_state"][base] = per_venue
                    holder["prices"][base] = _price_row(prices)
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
                if sink and status_every > 0 and holder["tick"] % status_every == 0:
                    n = orch.journal.decision_count()
                    sink.send(f"📊 AIMOS status: {holder['tick']} ticks, {n} decisions, "
                              f"{len(broker.positions())} open, equity {broker.equity():.0f} USDT")
            except Exception:  # noqa: BLE001 — the loop must never die
                log.exception("serve_loop_error")
            await asyncio.sleep(float(paper["loop_seconds"]))

    async def telegram_inbound() -> None:
        """Poll Telegram for commands (/enable, /pause, /status …) in this process."""
        bot = _build_telegram_bot(holder["features"], orch, broker, feature_ctl, clock)
        if bot is None:
            return
        log.info("telegram_inbound_started")
        while True:
            try:
                await asyncio.to_thread(bot.poll_once)
            except Exception:  # noqa: BLE001 — network hiccup shouldn't kill the poller
                log.exception("telegram_inbound_error")
            await asyncio.sleep(3.0)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(loop())
        tg_task = asyncio.create_task(telegram_inbound())
        log.info("serve_started", live_data=live_data, dashboard=DIST.exists(),
                 universe=holder["universe"].source, symbols=len(holder["universe"].selected))
        yield
        task.cancel()
        tg_task.cancel()
        ts_store.close()

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
        trades_provider=lambda: _trades_payload(broker, sim),
        balances_provider=lambda: _balances_payload(broker, sim, connections),
        connections_provider=lambda: {"venues": list(connections.values()),
                                      "any_live": any(c.get("connected") for c in connections.values())},
        performance_provider=lambda: _performance_payload(broker, sim, holder["equity"]),
        graph_provider=lambda did: _decision_graph(orch.journal, did, params),
        features_provider=feature_ctl.snapshot,
        feature_setter=feature_ctl.set,
        golive_provider=ladder.status,
        golive_setter=lambda gate, passed: ladder.mark(gate) if passed else ladder.unmark(gate),
    )
    app = create_app(state)
    app.router.lifespan_context = lifespan
    _mount_dashboard(app)
    return app


def _build_telegram_bot(features, orch, broker, feature_ctl, clock):
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
            feature_controller=feature_ctl,
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


def _maybe_arb(sim, primary_res, base, prices, now, paper, holder) -> None:
    """Execute a chosen cross-venue arb as two simulated legs (buy cheap/sell rich)."""
    if primary_res is None or primary_res.plan.action is Action.NO_TRADE:
        return
    m = primary_res.plan.meta
    if not m.get("cross_venue"):
        return
    bv, sv = m.get("buy_venue"), m.get("sell_venue")
    if bv not in prices or sv not in prices:
        return
    notional = float(primary_res.plan.size_quote or 0.0) or float(paper["starting_equity_usdt"]) * 0.01
    sim.execute_arb(base, bv, sv, prices[bv], prices[sv], notional, now)
    holder["chosen"]["CrossExchangeArb"] = holder["chosen"].get("CrossExchangeArb", 0) + 1


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
