"""FastAPI backend (§15.1, §16.2, §18.5, §24, card P5-T2).

Journal-backed reads; control endpoints are CONFIRM-gated (a typed "CONFIRM" in
the body, mirroring the UI modal and Telegram nonce flow). Metrics at /metrics.
The app is built from an injected ``AppState`` so it is testable with no live
runtime. Control actions are journaled with source="ui".
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aimos.auth.router import auth_router, user_router
from aimos.auth.security import AuthError, decode_token, FailedLoginTracker, get_current_user
from aimos.journal.journal import Journal


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


class ConnectionTestBody(BaseModel):
    venue: str = ""


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
    candles_provider: Any = None  # callable(symbol) -> {venues:[], candles:[]} (OHLC history)
    venue_state_provider: Any = None  # callable(symbol) -> {venue: {regime,p_up,action,...}}
    trades_provider: Any = None  # callable -> {"trades": [...]} (trade history)
    balances_provider: Any = None  # callable -> {"venues": [...]} (per-venue balances)
    performance_provider: Any = None  # callable -> perf metrics dict
    graph_provider: Any = None  # callable(decision_id) -> {"nodes": [...], "edges": [...]}
    connections_provider: Any = None  # callable -> {"venues": [...]} (Phase D preflight)
    connections_test_provider: Any = None  # callable(venue: str) -> preflight dict
    features_provider: Any = None  # callable -> {"features": {...}, "toggleable", "locked"}
    feature_setter: Any = None  # callable(name, value) -> {"ok", ...} (runtime toggle)
    golive_provider: Any = None  # callable -> go-live ladder status
    golive_setter: Any = None  # callable(gate, passed) -> {"ok", ...}
    monitor_provider: Any = None  # callable -> feature-monitor coverage report
    risk_provider: Any = None  # callable -> risk analytics report dict
    risk_analyzer: Any = None  # callable that recomputes and caches the risk report
    health_provider: Any = None  # callable -> readiness dict for /readyz
    control_store: Any = None  # ControlStore for cross-process control commands (REQ-13)
    auth_alert_tracker: Any = field(default_factory=FailedLoginTracker)  # failed-login alert state
    assistant: Any = None  # read-only AI analyst (Assistant) or None when disabled


def _decisions(journal: Journal, limit: int) -> list[dict]:
    rows = journal.conn.execute(
        'SELECT decision_id, symbol, "timestamp", payload FROM decisions ORDER BY seq DESC LIMIT ?',
        (limit,),
    ).fetchall()
    return [{"decision_id": r["decision_id"], "symbol": r["symbol"],
             "timestamp": r["timestamp"], "record": json.loads(r["payload"])} for r in rows]


def _runtime_org() -> str:
    return os.environ.get("AIMOS_RUNTIME_ORG_ID", "local")


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
    return request.cookies.get("access_token")


# Public paths: auth endpoints, the status probe, the static SPA shell + its
# client-side routes. Anything that is not a protected API route is treated as the
# SPA shell so the login page and assets can load (audit finding C2).
_PROTECTED_PREFIXES = ("/api/",)
_PROTECTED_EXACT = {"/metrics"}


def _is_public_path(path: str) -> bool:
    if path.startswith("/auth/") or path.startswith("/api/v2/"):
        return True
    if path in _PROTECTED_EXACT:
        return False
    return not path.startswith(_PROTECTED_PREFIXES)


def _is_control_path(path: str) -> bool:
    """State-changing / billable endpoints that must never be anonymous over the
    network (audit finding H1): the control actions and the LLM assistant."""
    return path.startswith("/api/control/") or path == "/api/assistant"


# "testclient" is Starlette's synthetic host for TestClient — not a routable
# network host, so allowing it keeps the in-process test suite green without
# widening the guard for real callers.
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "testclient"})


def _client_is_local(host: str | None) -> bool:
    return (host or "") in _LOCAL_HOSTS


# Fixed-window in-process throttle for the auth endpoints (audit finding H3).
# One uvicorn worker is the deployed topology, so per-process state is correct;
# multi-worker deployments would need a shared store. Structural constants.
_AUTH_WINDOW_SECONDS = 60.0
_AUTH_MAX_PER_WINDOW = 10


class _FixedWindowLimiter:
    """Thread-safe per-key request counter over a sliding time window."""

    def __init__(self, max_hits: int, window: float) -> None:
        self.max_hits = max_hits
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_hits:
                return False
            dq.append(now)
            return True


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="AIMOS API")

    @app.exception_handler(AuthError)
    async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=401)

    auth_limiter = _FixedWindowLimiter(_AUTH_MAX_PER_WINDOW, _AUTH_WINDOW_SECONDS)

    @app.middleware("http")
    async def throttle_auth(request: Request, call_next):
        """Rate-limit the auth endpoints per client IP (audit finding H3): bounds
        password/OTP brute force and the per-request bcrypt CPU-exhaustion vector
        against the process that also runs the trading loop."""
        if request.url.path.startswith("/auth/"):
            key = request.client.host if request.client else "unknown"
            if not auth_limiter.allow(key):
                return JSONResponse({"detail": "too many requests"}, status_code=429)
        return await call_next(request)

    @app.middleware("http")
    async def auth_scope(request: Request, call_next):
        """Single-user mode: protected endpoints need a valid access token.

        Auth endpoints, the public status/health probes, and the static SPA shell
        are exempt. Control actions (``/api/control/*`` and ``/api/assistant``)
        refuse non-loopback anonymous callers so a misconfigured public bind
        cannot expose the kill switch or go-live ladder (audit H1); loopback
        callers and any caller with a valid token are allowed.
        """
        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)
        is_local = _client_is_local(request.client.host if request.client else None)
        token = _extract_bearer(request)
        if token:
            try:
                decode_token(token, token_type="access")
            except AuthError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401)
            return await call_next(request)
        if _is_control_path(path) and not is_local:
            return JSONResponse(
                {"detail": "control requires authentication or a loopback client"},
                status_code=401,
            )
        if is_local:
            return await call_next(request)
        return JSONResponse({"detail": "Authorization required"}, status_code=401)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Add a default Content-Security-Policy and other hardening headers to
        every response (audit finding G3/G7). The policy allows inline styles
        because the dashboard uses element-level styles, but blocks external
        scripts, frames, and object/embed sources."""
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.get("/api/v2/status")
    def status():
        """Public status endpoint: runtime flags and halt state."""
        features = state.features_provider() if state.features_provider else {"features": {}}
        return {
            "single_user": True,
            "features": features.get("features", {}),
            "halted": features.get("halted", False),
        }

    @app.get("/healthz")
    def healthz():
        """Public liveness probe — process is responding."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        """Public readiness probe — journal writable and trading loop heartbeat fresh."""
        if state.health_provider:
            payload = state.health_provider()
            if not payload.get("ready"):
                raise HTTPException(status_code=503, detail=payload)
            return payload
        return {"status": "ok"}

    @app.get("/api/state/{symbol}")
    def get_state(symbol: str):
        mu = state.latest_state.get(symbol)
        if mu is None:
            raise HTTPException(status_code=404, detail="no state for symbol")
        return mu

    @app.get("/api/decisions")
    def get_decisions(limit: int = Query(50, ge=1, le=500)):
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

    def _persist_controls(controls: dict[str, Any]) -> None:
        if state.control_store:
            current = state.control_store.load()
            current.update(controls)
            state.control_store.save(current)

    @app.post("/api/control/pause")
    def pause(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.pause(body.symbol)
            _persist_controls({
                "global_pause": state.orchestrator.state.global_pause,
                "paused_assets": sorted(state.orchestrator.state.paused_assets),
            })
        return {"ok": True, "paused": body.symbol or "global"}

    @app.post("/api/control/resume")
    def resume(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.resume(body.symbol)
            _persist_controls({
                "global_pause": state.orchestrator.state.global_pause,
                "paused_assets": sorted(state.orchestrator.state.paused_assets),
            })
        return {"ok": True, "resumed": body.symbol or "global"}

    @app.post("/api/control/killswitch")
    def killswitch(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.halt()
            _persist_controls({"halted": True})
        return {"ok": True, "halted": True}

    @app.post("/api/control/unhalt")
    def unhalt(body: ConfirmBody):
        _require_confirm(body)
        if state.orchestrator:
            state.orchestrator.unhalt()
            _persist_controls({"halted": False})
        return {"ok": True, "halted": False}

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

    @app.get("/api/candles/{symbol}")
    def get_candles(symbol: str):
        # OHLC history for the chosen symbol (Candlestick chart, §5.1)
        return state.candles_provider(symbol) if state.candles_provider else {"venues": [], "candles": []}

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

    @app.post("/api/connections/test")
    def test_connection(body: ConnectionTestBody):
        # run a fresh read-only preflight for one venue using stored credentials
        if not state.connections_test_provider:
            raise HTTPException(status_code=503, detail="connection testing unavailable")
        result = state.connections_test_provider(body.venue)
        if not result:
            raise HTTPException(status_code=404, detail=f"no credentials for {body.venue}")
        return result

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

    @app.get("/api/risk")
    def get_risk():
        # VaR/ES, alpha/beta vs BTC & T1 basket, BTC-beta factor split (§24.3-24.4)
        report = state.risk_provider() if state.risk_provider else {}
        if not report and state.risk_analyzer:
            report = state.risk_analyzer()
        return report

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

    @app.get("/api/assistant/debate/{decision_id}")
    def assistant_debate(decision_id: str):
        # post-hoc case-for / case-against narrative for a completed decision (REQ-19)
        if state.assistant is None:
            raise HTTPException(status_code=503,
                                detail="assistant disabled (set assistant.enabled + ANTHROPIC_API_KEY)")
        try:
            return state.assistant.debate(decision_id)
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

    app.include_router(auth_router)
    app.include_router(user_router)

    # Expose the injected state and failed-login tracker to request-time code.
    app.state.aimos = state
    app.state.auth_alert_tracker = state.auth_alert_tracker
    return app


def _require_confirm(body: ConfirmBody) -> None:
    if body.confirm != "CONFIRM":
        raise HTTPException(status_code=403, detail="control requires confirm='CONFIRM'")


def _prometheus(metrics: dict[str, float]) -> str:
    from fastapi.responses import PlainTextResponse
    lines = [f"{k} {v}" for k, v in metrics.items()]
    return PlainTextResponse("\n".join(lines) + "\n")


__all__ = ["AppState", "create_app"]
