"""Telegram security/notifier + FastAPI backend + ops reconciliation tests
(§15.2, §15.1, §23.5-23.6 — cards P5-T4, P5-T2, P5-T8)."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aimos.api.server import AppState, create_app
from aimos.core.schemas import Action, DecisionRecord, TradePlan
from aimos.journal.journal import Journal
from aimos.runtime.reconciliation import reconcile_accounting, reconcile_positions
from aimos.telegram.notifier import Deduper, fmt_trade_opened
from aimos.telegram.security import ChatWhitelist, NonceStore
from tests.conftest import FakeClock, make_mu

ROOT = Path(__file__).resolve().parents[1]
TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


# ---- telegram security (P5-T4) ----

def test_whitelist_blocks_unknown():
    wl = ChatWhitelist({111, 222})
    assert wl.is_allowed(111)
    assert not wl.is_allowed(999)  # unknown → silent ignore upstream


def test_nonce_confirm_flow():
    clock = FakeClock(TS)
    store = NonceStore(clock, ttl_seconds=60)
    nonce = store.create(chat_id=111, command="/killswitch")
    # wrong chat cannot confirm
    ok, _ = store.confirm(chat_id=222, nonce=nonce)
    assert not ok
    # correct chat confirms
    ok, cmd = store.confirm(chat_id=111, nonce=nonce)
    assert ok and cmd == "/killswitch"


def test_nonce_expiry():
    clock = FakeClock(TS)
    store = NonceStore(clock, ttl_seconds=60)
    nonce = store.create(111, "/flatten SOL")
    clock.advance(61)  # past TTL
    ok, _ = store.confirm(111, nonce)
    assert not ok


def test_notifier_dedupe_except_trades():
    clock = FakeClock(TS)
    d = Deduper(clock, window_seconds=300)
    assert d.should_send("regime_change", "BTC")
    assert not d.should_send("regime_change", "BTC")  # within window → deduped
    clock.advance(301)
    assert d.should_send("regime_change", "BTC")  # window passed
    # trade events always send
    assert d.should_send("trade_opened", "BTC")
    assert d.should_send("trade_opened", "BTC")


def test_notifier_template():
    msg = fmt_trade_opened("LONG", "SOL", "TrendFollowing", 150, 145.75, 160.6, 66, 2.5, 30, "BOS + volume")
    assert "OPENED LONG SOL" in msg and "TrendFollowing" in msg


# ---- FastAPI backend (P5-T2) ----

def _app_state():
    j = Journal(":memory:")
    plan = TradePlan(plugin="RiskOff", symbol="SOL", action=Action.NO_TRADE)
    j.write_decision(DecisionRecord(timestamp=TS, symbol="SOL", understanding=make_mu(),
                                    candidates=[], chosen=plan, mode="paper", decision_id="SOL-1"))
    return AppState(journal=j, latest_state={"SOL": make_mu().model_dump(mode="json")})


def test_api_decisions_and_state():
    client = TestClient(create_app(_app_state()))
    r = client.get("/api/decisions?limit=10")
    assert r.status_code == 200 and len(r.json()["decisions"]) == 1
    r = client.get("/api/state/SOL")
    assert r.status_code == 200 and r.json()["symbol"] == "SOL"
    assert client.get("/api/state/UNKNOWN").status_code == 404


def test_api_anatomy_from_journal():
    client = TestClient(create_app(_app_state()))
    r = client.get("/api/decision/SOL-1/anatomy")
    assert r.status_code == 200
    # anatomy is generated purely from the journaled record (§16.2)
    assert r.json()["understanding"]["symbol"] == "SOL"


def test_api_control_requires_confirm():
    client = TestClient(create_app(_app_state()))
    # without confirm → rejected
    assert client.post("/api/control/killswitch", json={}).status_code == 403
    assert client.post("/api/control/pause", json={"confirm": "nope"}).status_code == 403
    # with confirm → accepted
    r = client.post("/api/control/pause", json={"confirm": "CONFIRM"})
    assert r.status_code == 200 and r.json()["ok"]


def test_api_control_unhalt():
    client = TestClient(create_app(_app_state()))
    # no orchestrator means stateless ok, but we can still call unhalt
    r = client.post("/api/control/unhalt", json={"confirm": "CONFIRM"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "halted": False}


def test_api_metrics_endpoint():
    client = TestClient(create_app(_app_state()))
    r = client.get("/metrics")
    assert r.status_code == 200 and "aimos_decisions_total" in r.text


def test_api_ui_endpoints_serve_dashboard():
    # every endpoint the React dashboard calls responds (§16.2 screens)
    state = _app_state()
    state.effective_config = {"mode": "paper"}
    state.matrix_provider = lambda: {"BTC": {"binance": True, "kraken": True}}
    client = TestClient(create_app(state))
    assert client.get("/api/markets").json()["markets"][0]["symbol"] == "SOL"
    assert client.get("/api/universe/matrix").json()["BTC"]["binance"] is True
    assert client.get("/api/config/effective").json()["mode"] == "paper"
    assert "agents" in client.get("/api/agents").json()
    assert "proposals" in client.get("/api/proposals").json()


def test_dashboard_build_present_if_built():
    # if the operator ran `npm run build`, dist/ exists; otherwise skip (Node build)
    dist = ROOT / "dashboard" / "dist" / "index.html"
    if dist.exists():
        assert "root" in dist.read_text()


# ---- ops reconciliation (P5-T8) ----

def test_reconcile_positions_adopt_and_close_unknown():
    res = reconcile_positions(exchange_symbols=["BTC", "ETH"], journal_symbols=["BTC", "SOL"])
    assert res.matched == ["BTC"]
    assert res.adopt == ["ETH"]          # on exchange, not journal → adopt
    assert res.close_unknown == ["SOL"]  # in journal, not exchange → closed-unknown
    assert not res.consistent
    assert len(res.alerts) == 2


def test_reconcile_accounting_divergence_halts():
    res = reconcile_accounting({"fees": 100.0}, {"fees": 105.0}, tolerance_usd=1.0)
    assert res.halt_pnl_jobs  # $5 > $1 → halt PnL-dependent jobs
    res2 = reconcile_accounting({"fees": 100.0}, {"fees": 100.5}, tolerance_usd=1.0)
    assert not res2.halt_pnl_jobs
