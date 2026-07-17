"""Phase B: simulated multi-venue arb execution + trade history + balances + perf."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from aimos.execution.broker.multivenue import MultiVenueSim, performance
from aimos.runtime.serve import build_app


def test_arb_two_leg_execution_and_balances():
    sim = MultiVenueSim(venues=["binance", "kraken"], start_usdt_total=10_000.0, taker_bps=7.5)
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    # buy cheap (100) / sell rich (100.6) → ~60bps gross, ~45bps net after 15bps round trip
    pnl = sim.execute_arb("BTC", "binance", "kraken", 100.0, 100.6, 1_000.0, now)
    assert pnl > 0                          # profitable spread capture
    assert len(sim.trades) == 1
    t = sim.trades[0]
    assert t["kind"] == "arb" and t["venue"] == "binance→kraken"
    # USDT shifts from buy venue to sell venue (the inventory-rebalance reality)
    rows = {r["venue"]: r["usdt"] for r in sim.balances_rows()}
    assert rows["binance"] < 5_000.0 and rows["kraken"] > 5_000.0
    assert abs(sim.total_usdt() - (10_000.0 + pnl)) < 1e-6


def test_performance_aggregates_by_strategy_and_venue():
    arb = [{"kind": "arb", "symbol": "BTC", "strategy": "CrossExchangeArb",
            "venue": "binance→kraken", "pnl_usd": 5.0, "status": "closed"}]
    directional = [{"kind": "directional", "symbol": "ETH", "strategy": "TrendFollowing",
                    "venue": "binance", "pnl_usd": -2.0, "status": "closed"}]
    p = performance(directional, arb, [10_000.0, 10_003.0, 10_001.0])
    assert p["closed_trades"] == 2
    assert p["win_rate"] == 0.5
    assert p["arb_pnl_usd"] == 5.0
    assert p["by_strategy"]["CrossExchangeArb"]["pnl_usd"] == 5.0
    assert p["max_drawdown_pct"] > 0  # 10003 → 10001


def test_decision_graph_has_engine_to_chosen_path():
    app = build_app(offline=True)
    with TestClient(app) as c:
        time.sleep(2)
        did = c.get("/api/decisions?limit=1").json()["decisions"][0]["decision_id"]
        g = c.get(f"/api/decision/{did}/graph").json()
        kinds = {n["kind"] for n in g["nodes"]}
        assert {"engine", "fusion", "regime", "strategy", "decision"} <= kinds
        assert {n["layer"] for n in g["nodes"]} == {0, 1, 2, 3, 4}  # full left→right path
        # exactly one chosen node highlighted at the decision layer
        chosen = [n for n in g["nodes"] if n["kind"] == "decision"]
        assert len(chosen) == 1 and chosen[0]["highlight"]
        # every edge references real nodes
        ids = {n["id"] for n in g["nodes"]}
        assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])


def test_serve_executes_arb_and_serves_trade_history():
    import os
    os.environ["AIMOS__FEATURES__CROSS_EXCHANGE_ENABLED"] = "true"
    os.environ["AIMOS__PLUGINS__CROSS_EXCHANGE_ARB__ENABLED"] = "true"
    try:
        app = build_app(offline=True)
        with TestClient(app) as c:
            time.sleep(5)
            trades = c.get("/api/trades").json()
            arb = [t for t in trades["trades"] if t["kind"] == "arb"]
            assert arb, "expected at least one executed cross-venue arb"
            assert "→" in arb[0]["venue"]  # buy→sell venue pair
            bal = c.get("/api/balances").json()
            assert len(bal["venues"]) >= 2 and bal["total_usdt"] > 0
            perf = c.get("/api/performance").json()
            assert perf["arb_trades"] >= 1 and "by_venue" in perf
    finally:
        for k in ("AIMOS__FEATURES__CROSS_EXCHANGE_ENABLED", "AIMOS__PLUGINS__CROSS_EXCHANGE_ARB__ENABLED"):
            os.environ.pop(k, None)
