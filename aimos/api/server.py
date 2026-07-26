"""FastAPI backend (§15.1, §16.2, §18.5, §24, card P5-T2).

Journal-backed reads; control endpoints are CONFIRM-gated (a typed "CONFIRM" in
the body, mirroring the UI modal and Telegram nonce flow). Metrics at /metrics.
The app is built from an injected ``AppState`` so it is testable with no live
runtime. Control actions are journaled with source="ui".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aimos.journal.journal import Journal
from aimos.saas.router import auth_router, tenant_router
from aimos.saas.settings import get_saas_config


class ConfirmBody(BaseModel):
    confirm: str = ""
    symbol: Optional[str] = None


class FeatureBody(BaseModel):
    confirm: str = ""
    name: str = ""
    enabled: bool = False


class GoLiveBody(BaseModel):
    confirm: str = ""
    gate: str = ""
    passed: bool = True


class AskBody(BaseModel):
    question: str = ""


@dataclass
class AppState:
    """Everything the API reads/controls — injected so the backend is testable."""

    journal: Journal
    orchestrator: Any = None  # PipelineOrchestrator (pause/resume/halt)
    positions_provider: Any = None  # callable -> list[dict]
    equity_provider: Any = None  # callable -> list[float]
    latest_state: dict = field(default_factory=dict)  # symbol -> MarketUnderstanding dict
    matrix_provider: Any = None  # callable -> universe payload {matrix,tiers,rejections,...}
    effective_config: dict = field(default_factory=dict)  # §16.2 Screen 8
    agents_provider: Any = None  # callable -> {"agents": [...]}
    proposals_provider: Any = None  # callable -> {"proposals": [...]}
    evidence_provider: Any = None  # callable(symbol, venue) -> {"evidences": [...]} (13 engines)
    strategies_provider: Any = None  # callable -> {"strategies": [...]} (execution plugins)
    models_provider: Any = None  # callable -> {"models": [...]} (rule/bayes/ml + learning)
    prices_provider: Any = None  # callable -> {"venues": [...], "rows": [...]} (price matrix)
    venue_state_provider: Any = None  # callable(symbol) -> {venue: {regime,p_up,action,...}}
    trades_provider: Any = None  # callable -> {"trades": [...]} (trade history)
    balances_provider: Any = None  # callable -> {"venues": [...]} (per-venue balances)
    performance_provider: Any = None  # callable -> perf metrics dict
    graph_provider: Any = None  # callable(decision_id) -> {"nodes": [...], "edges": [...]}
    connections_provider: Any = None  # callable -> {"venues": [...]} (Phase D preflight)
    features_provider: Any = None  # callable -> {"features": {...}, "toggleable", "locked"}
    feature_setter: Any = None  # callable(name, value) -> {"ok", ...} (runtime toggle)
    golive_provider: Any = None  # callable -> go-live ladder status
    golive_setter: Any = None  # callable(gate, passed) -> {"ok", ...}
    monitor_provider: Any = None  # callable -> feature-monitor coverage report
    assistant: Any = None  # read-only AI analyst (Assistant) or None when disabled


def _decisions(journal: Journal, limit: int) -> list[dict]:
    rows = journal.conn.execute(
        "SELECT decision_id, symbol, timestamp, payload FROM decisions ORDER BY seq DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"decision_id": r["decision_id"], "symbol": r["symbol"],
             "timestamp": r["timestamp"], "record": json.loads(r["payload"])} for r in rows]


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="AIMOS API")

    @app.get("/api/v2/status")
    def status():
        """Public status endpoint so the dashboard can detect SaaS mode."""
        return {"saas_enabled": get_saas_config().enabled}

    @app.get("/api/state/{symbol}")
    def get_state(symbol: str):
        mu = state.latest_state.get(symbol)
        if mu is None:
            raise HTTPException(status_code=404, detail="no state for symbol")
        return mu

    @app.get("/api/decisions")
    def get_decisions(limit: int = 50):
        return {"decisions": _decisions(state.journal, limit)}

    @app.get("/api/decision/{decision_id}/graph")
    def get_graph(decision_id: str):
        # mind-map node/edge graph of one decision (§5.3)
        return state.graph_provider(decision_id) if state.graph_provider else {"nodes": [], "edges": []}

    @app.get("/api/decision/{decision_id}/anatomy")
    def get_anatomy(decision_id: str):
        row = state.journal.conn.execute(
            "SELECT payload FROM decisions WHERE decision_id = ? LIMIT 1", (decision_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown decision")
        rec = json.loads(row["payload"])
        # Screen-3 anatomy is generated purely from the journaled record (§16.2)
        return {"decision_id": decision_id, "understanding": rec["understanding"],
                "chosen": rec["chosen"], "candidates": rec["candidates"]}

    @app.get("/api/positions")
    def get_positions():
        return {"positions": state.positions_provider() if state.positions_provider else []}

    @app.get("/api/equity")
    def get_equity():
        return {"equity": state.equity_provider() if state.equity_provider else []}

    @app.get("/api/journal/stats")
    def get_stats():
        n = state.journal.decision_count()
        traded = state.journal.conn.execute(
            "SELECT COUNT(*) c FROM decisions WHERE payload LIKE '%\"action\":\"long\"%'"
            " OR payload LIKE '%\"action\":\"short\"%'"
        ).fetchone()["c"]
        return {"n_decisions": n, "n_traded": traded,
                "no_trade_rate": (n - traded) / n if n else 0.0}

    @app.post("/api/control/pause")
    def pause(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.pause(body.symbol)
        return {"ok": True, "paused": body.symbol or "global"}

    @app.post("/api/control/resume")
    def resume(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.resume(body.symbol)
        return {"ok": True, "resumed": body.symbol or "global"}

    @app.post("/api/control/killswitch")
    def killswitch(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.state.halted = True
        return {"ok": True, "halted": True}

    @app.get("/api/markets")
    def get_markets():
        # latest MarketUnderstanding per symbol (Screen 1, §16.2)
        return {"markets": [{"symbol": s, **v} for s, v in state.latest_state.items()]}

    @app.get("/api/universe/matrix")
    def get_matrix():
        return state.matrix_provider() if state.matrix_provider else {}

    @app.get("/api/config/effective")
    def get_config():
        return state.effective_config

    @app.get("/api/evidence/{symbol}")
    def get_evidence(symbol: str, venue: Optional[str] = None):
        # per-engine evidence for the latest tick, per venue (Engines screen, §5/§16.2)
        return state.evidence_provider(symbol, venue) if state.evidence_provider else {"evidences": []}

    @app.get("/api/prices/matrix")
    def get_prices():
        # per-coin per-venue mids + dislocation (multi-platform price matrix, §5.1)
        return state.prices_provider() if state.prices_provider else {"venues": [], "rows": []}

    @app.get("/api/venue_state/{symbol}")
    def get_venue_state(symbol: str):
        # per-venue regime/p_up/action for one coin (§3.1 per-venue decisions)
        return state.venue_state_provider(symbol) if state.venue_state_provider else {}

    @app.get("/api/trades")
    def get_trades():
        # directional + cross-venue arb trades (Trade History, §5.5)
        return state.trades_provider() if state.trades_provider else {"trades": []}

    @app.get("/api/balances")
    def get_balances():
        # per-venue simulated balances (Balance check, §5.4)
        return state.balances_provider() if state.balances_provider else {"venues": []}

    @app.get("/api/performance")
    def get_performance():
        # realized PnL / win-rate / per-strategy / per-venue (Performance, §5.6)
        return state.performance_provider() if state.performance_provider else {}

    @app.get("/api/connections")
    def get_connections():
        # per-venue read-only preflight status (Phase D §2.4) — never exposes secrets
        return state.connections_provider() if state.connections_provider else {"venues": []}

    @app.get("/api/features")
    def get_features():
        # current runtime flags + which are toggleable vs locked
        return state.features_provider() if state.features_provider else {"features": {}}

    @app.get("/api/golive")
    def get_golive():
        # go-live ladder progress (§23.8)
        return state.golive_provider() if state.golive_provider else {"gates": [], "percent": 0}

    @app.get("/api/monitor")
    def get_monitor():
        # feature-monitor coverage report: per-feature ok/degraded/failing + coverage %
        return state.monitor_provider() if state.monitor_provider else {
            "features": [], "summary": {}, "coverage_pct": 0.0}

    @app.get("/api/assistant")
    def assistant_status():
        # whether the read-only analyst is available (enabled + API key)
        return {"enabled": state.assistant is not None}

    @app.post("/api/assistant")
    def assistant_ask(body: AskBody):
        # read-only AI analyst — grounded Q&A over the journal + metrics (§15.3)
        if state.assistant is None:
            raise HTTPException(status_code=503,
                                detail="assistant disabled (set assistant.enabled + ANTHROPIC_API_KEY)")
        try:
            return state.assistant.answer(body.question)
        except Exception as exc:  # noqa: BLE001 — surface LLM/config errors as 502
            raise HTTPException(status_code=502, detail=f"assistant error: {exc}")

    @app.get("/api/assistant/report")
    def assistant_report(timeframe: str = "24h"):
        # grounded performance + health report for a timeframe (e.g. 24h, 7d)
        if state.assistant is None:
            raise HTTPException(status_code=503,
                                detail="assistant disabled (set assistant.enabled + ANTHROPIC_API_KEY)")
        try:
            return state.assistant.report(timeframe)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"assistant error: {exc}")

    @app.post("/api/control/golive")
    def set_golive(body: GoLiveBody):
        # operator sign-off on a go-live gate — CONFIRM-gated
        _require_confirm(body)
        if not state.golive_setter:
            raise HTTPException(status_code=503, detail="go-live control unavailable")
        res = state.golive_setter(body.gate, body.passed)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("error", "rejected"))
        return res

    @app.post("/api/control/feature")
    def set_feature(body: FeatureBody):
        # runtime feature toggle — CONFIRM-gated; refuses locked (live/funded) flags
        _require_confirm(body)
        if not state.feature_setter:
            raise HTTPException(status_code=503, detail="feature control unavailable")
        res = state.feature_setter(body.name, body.enabled)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("error", "toggle rejected"))
        return res

    @app.get("/api/strategies")
    def get_strategies():
        # execution plugins: config + how often each was chosen (Strategies screen, §7)
        return state.strategies_provider() if state.strategies_provider else {"strategies": []}

    @app.get("/api/models")
    def get_models():
        # reasoning models rule/bayes/ml + learning status (Models screen, §6/§8)
        return state.models_provider() if state.models_provider else {"models": []}

    @app.get("/api/agents")
    def get_agents():
        return state.agents_provider() if state.agents_provider else {"agents": []}

    @app.get("/api/proposals")
    def get_proposals():
        return state.proposals_provider() if state.proposals_provider else {"proposals": []}

    @app.get("/metrics")
    def metrics():
        n = state.journal.decision_count()
        return _prometheus({"aimos_decisions_total": n})

    if get_saas_config().enabled:
        app.include_router(auth_router)
        app.include_router(tenant_router)

    return app


def _require_confirm(body: ConfirmBody) -> None:
    if body.confirm != "CONFIRM":
        raise HTTPException(status_code=403, detail="control requires confirm='CONFIRM'")


def _prometheus(metrics: dict[str, float]) -> str:
    from fastapi.responses import PlainTextResponse
    lines = [f"{k} {v}" for k, v in metrics.items()]
    return PlainTextResponse("\n".join(lines) + "\n")


__all__ = ["AppState", "create_app"]
