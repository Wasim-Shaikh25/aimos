"""Universe wiring into the runtime + the engines/strategies/models endpoints.

Covers issue set: the loop analyzes the discovered/seeded universe (not just the
2-symbol dev set), the cross-venue matrix is exposed, and the backend richness
(per-engine evidence, strategies, models) is reachable over the API.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from aimos.core.config import load_params
from aimos.data.universe_source import build_universe
from aimos.runtime.serve import build_app


def test_universe_seed_offline_selects_top_n():
    p = load_params().model_dump()
    uni = build_universe("binance", p["universe"], live_data=False, max_symbols=40)
    assert uni.source == "seed"
    assert uni.total_discovered > 40           # full universe discovered
    assert len(uni.selected) == 40             # top-N analyzed
    assert uni.selected[0] == "BTC"            # volume-rank order preserved
    # cross-venue intersection surfaces multi-venue assets (issue: cross-platform)
    assert "BTC" in uni.cross_venue_bases(2)
    m = uni.matrix()
    assert set(m["BTC"]) >= {"binance", "kraken"}


def test_universe_leveraged_tokens_rejected():
    p = load_params().model_dump()
    uni = build_universe("binance", p["universe"], live_data=False, max_symbols=200)
    # JUP ends in "UP" → caught by the leveraged-token filter (§16.1 B)
    assert uni.rejections.get("leveraged", 0) >= 1


def test_serve_exposes_full_universe_and_backend_richness():
    app = build_app(offline=True)
    with TestClient(app) as c:
        time.sleep(2.5)  # let a couple of ticks populate

        # issue 1: many coins, not just BTC/ETH
        markets = c.get("/api/markets").json()["markets"]
        assert len(markets) > 10
        syms = {m["symbol"] for m in markets}
        assert {"BTC", "ETH", "SOL"} <= syms

        # issue 2: cross-platform surfaced (multi-venue matrix + venues)
        u = c.get("/api/universe/matrix").json()
        assert u["total_discovered"] > 40
        assert len(u["cross_venues"]) >= 2
        assert u["matrix"]["BTC"]["kraken"] is True

        # issue 4: engines / strategies / models visible
        strat = c.get("/api/strategies").json()["strategies"]
        names = {s["name"] for s in strat}
        assert {"RiskOff", "TrendFollowing", "CrossExchangeArb"} <= names
        models = c.get("/api/models").json()["models"]
        assert {m["name"] for m in models} == {"RuleEngine", "BayesEngine", "MLEngine"}
        # ml stays in shadow (fusion weight 0) by default (§8.3)
        ml = next(m for m in models if m["name"] == "MLEngine")
        assert ml["fusion_weight"] in (0, 0.0)
        ev = c.get("/api/evidence/BTC").json()["evidences"]
        assert ev and all("name" in e and "reliability" in e for e in ev)
