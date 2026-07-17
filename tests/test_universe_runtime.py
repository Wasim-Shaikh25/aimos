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


def test_cross_venue_bias_drops_single_venue_coins():
    p = load_params().model_dump()
    plain = build_universe("binance", p["universe"], live_data=False, max_symbols=40)
    biased = build_universe("binance", p["universe"], live_data=False, max_symbols=40,
                            prefer_cross_venue=True, min_venues=2)
    # BNB is single-venue in the seed → present without bias, gone with it
    assert "BNB" in plain.selected
    assert "BNB" not in biased.selected
    # every biased pick trades on ≥ 2 venues
    cross = biased.cross_venue_bases(2)
    assert all(b in cross for b in biased.selected)


def test_venue_snapshot_uses_each_coins_actual_venues():
    from datetime import datetime, timezone
    from aimos.data.live_source import venue_snapshot_for
    p = load_params()
    uni = build_universe("binance", p.universe.model_dump(), live_data=False, max_symbols=40)
    feats, paper = {"cross_exchange_enabled": True}, p.paper.model_dump()
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    # BTC trades on 3 venues → snapshot spans all 3 (not a fixed 2-venue list)
    btc = venue_snapshot_for(feats, paper, uni.registry, "BTC/USDT", 30_000.0, now, live_data=False)
    assert set(btc) == {"binance", "kraken", "coinbase"}
    # a single-venue coin can't be arbitraged → skipped
    assert venue_snapshot_for(feats, paper, uni.registry, "BNB/USDT", 600.0, now, live_data=False) is None
    # disabled flag → always None
    assert venue_snapshot_for({}, paper, uni.registry, "BTC/USDT", 1.0, now, live_data=False) is None


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


def test_serve_per_venue_analysis_and_price_matrix():
    import os
    os.environ["AIMOS__FEATURES__CROSS_EXCHANGE_ENABLED"] = "true"
    try:
        app = build_app(offline=True)
        with TestClient(app) as c:
            time.sleep(3)
            # §3.1 full analysis per venue → each coin decided on every venue it trades on
            pm = c.get("/api/prices/matrix").json()
            assert set(pm["venues"]) >= {"binance", "kraken", "coinbase"}
            btc = next(r for r in pm["rows"] if r["base"] == "BTC")
            assert set(btc["venues"]) >= {"binance", "kraken", "coinbase"}  # per-venue mids
            # realistic dislocation (bps, not tens of %)
            assert 0 < btc["dislocation_bps"] < 200
            assert btc["cheap"] != btc["rich"]
            # per-venue decision present for each venue
            vs = c.get("/api/venue_state/BTC").json()
            assert set(vs) >= {"binance", "kraken", "coinbase"}
            assert all("action" in d and "regime" in d for d in vs.values())
            # per-venue evidence selectable
            ek = c.get("/api/evidence/BTC?venue=kraken").json()
            assert ek["evidences"] and "kraken" in ek["venues"]
    finally:
        os.environ.pop("AIMOS__FEATURES__CROSS_EXCHANGE_ENABLED", None)
