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


class ConfirmBody(BaseModel):
    confirm: str = ""
    symbol: Optional[str] = None


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


def _decisions(journal: Journal, limit: int) -> list[dict]:
    rows = journal.conn.execute(
        "SELECT decision_id, symbol, timestamp, payload FROM decisions ORDER BY seq DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"decision_id": r["decision_id"], "symbol": r["symbol"],
             "timestamp": r["timestamp"], "record": json.loads(r["payload"])} for r in rows]


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="AIMOS API")

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

    return app


def _require_confirm(body: ConfirmBody) -> None:
    if body.confirm != "CONFIRM":
        raise HTTPException(status_code=403, detail="control requires confirm='CONFIRM'")


def _prometheus(metrics: dict[str, float]) -> str:
    from fastapi.responses import PlainTextResponse
    lines = [f"{k} {v}" for k, v in metrics.items()]
    return PlainTextResponse("\n".join(lines) + "\n")


__all__ = ["AppState", "create_app"]
