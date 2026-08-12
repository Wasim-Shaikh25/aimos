"""P8 CrossExchangeArb + multi-venue wiring (§5.11, §7.2 P8).

Covers: the arb plugin geometry/economics, the disabled-by-default posture,
enabling via config, and the end-to-end path
synthetic venue_snapshot → CrossExchangeEngine.price_dislocation →
IntelligenceLayer.key_levels["dislocation"] → CrossExchangeArb.propose.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Action, EvidenceBundle, Timeframe, VenueTop
from aimos.data.context import build_context
from aimos.data.live_source import (
    live_venue_snapshot,
    synthetic_venue_snapshot,
)
from aimos.execution.plugins import CrossExchangeArb, build_plugins
from aimos.intelligence.understand import IntelligenceLayer
from aimos.observation.cross_exchange import CrossExchangeEngine, compute_dislocation
from tests.conftest import FakeClock, make_exec_ctx, make_mu, obs_cfg, reliability

_ARB_CFG = {
    "enabled": True, "min_confidence": 0.0, "min_coin_health": 0.0,
    "extra_margin_bps": 4, "stop_bps": 10, "hold_minutes": 15, "arb_confidence": 0.85,
}


def _arb() -> CrossExchangeArb:
    return CrossExchangeArb(_ARB_CFG)


# -- plugin economics --------------------------------------------------------


def test_arb_proposes_when_dislocation_clears_costs_and_margin():
    # costs = 7.5*2 + 2 + 2 = 19bps; +margin 4 => needs > 23bps. Use 40bps.
    mu = make_mu(key_levels={"price": 150.0, "atr": 2.1,
                             "dislocation": {"bps": 40.0, "buy_venue": "kraken",
                                             "sell_venue": "binance"}})
    plan = _arb().propose(mu, make_exec_ctx())
    assert plan is not None
    assert plan.action is Action.LONG and plan.plugin == "CrossExchangeArb"
    net = 40.0 - 19.0 - 4.0  # 17 bps net capture (round-trip costs netted into tp)
    assert plan.take_profit == 150.0 * (1 + net / 10_000.0)
    assert plan.stop_loss == 150.0 * (1 - 10 / 10_000.0)
    assert abs(plan.expected_rr - net / 10.0) < 1e-9
    assert plan.expected_costs_bps == 0.0  # costs self-accounted (no double-count)
    assert plan.meta["cross_venue"] is True
    assert plan.meta["buy_venue"] == "kraken" and plan.meta["sell_venue"] == "binance"
    assert abs(plan.meta["net_capture_bps"] - net) < 1e-9


def test_arb_skips_when_spread_below_cost_floor():
    mu = make_mu(key_levels={"price": 150.0,
                             "dislocation": {"bps": 20.0, "buy_venue": "kraken",
                                             "sell_venue": "binance"}})
    assert _arb().propose(mu, make_exec_ctx()) is None  # 20 < 19 + 4


def test_arb_skips_without_two_distinct_venues():
    mu_same = make_mu(key_levels={"price": 150.0,
                                  "dislocation": {"bps": 40.0, "buy_venue": "binance",
                                                  "sell_venue": "binance"}})
    assert _arb().propose(mu_same, make_exec_ctx()) is None
    mu_none = make_mu(key_levels={"price": 150.0})  # no dislocation surfaced
    assert _arb().propose(mu_none, make_exec_ctx()) is None


def test_arb_is_regime_agnostic():
    # any regime — a ranging book still arbs if the spread is real
    from aimos.core.schemas import Regime
    mu = make_mu(regime=Regime.RANGING, regime_probs={"ranging": 1.0},
                 key_levels={"price": 150.0,
                             "dislocation": {"bps": 40.0, "buy_venue": "kraken",
                                             "sell_venue": "binance"}})
    assert _arb().can_trade(mu) is True
    assert _arb().propose(mu, make_exec_ctx()) is not None


# -- config posture ----------------------------------------------------------


def test_arb_disabled_by_default_but_registered():
    params = load_params()
    names = [p.name for p in build_plugins(params)]
    assert "CrossExchangeArb" not in names  # enabled:false in shipped config


def test_arb_built_when_enabled():
    params = load_params()
    params.plugins["cross_exchange_arb"].enabled = True  # type: ignore[attr-defined]
    names = [p.name for p in build_plugins(params)]
    assert "CrossExchangeArb" in names


# -- multi-venue data + end-to-end path --------------------------------------


def test_synthetic_snapshot_has_measurable_dislocation():
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    snap = synthetic_venue_snapshot("BTC/USDT", 30_000.0, now, ["binance", "kraken"],
                                    dislocation_bps=40.0, clock=FakeClock(now))
    assert set(snap) == {"binance", "kraken"}
    mids = sorted(t.mid for t in snap.values())
    gap_bps = (mids[1] - mids[0]) / ((mids[0] + mids[1]) / 2) * 10_000.0
    assert 35.0 < gap_bps < 45.0  # ~40bps apart


def test_live_snapshot_uses_injected_fetchers_and_skips_failures():
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)

    class _OK:
        def __init__(self, bid, ask):
            self._b, self._a = bid, ask

        def fetch_top_of_book(self, symbol):
            return self._b, self._a

    class _Dead:
        def fetch_top_of_book(self, symbol):
            raise RuntimeError("venue down")

    snap = live_venue_snapshot(
        "BTC/USDT", now, ["binance", "kraken", "coinbase"],
        fetchers={"binance": _OK(100.0, 100.2), "kraken": _OK(100.3, 100.5),
                  "coinbase": _Dead()},
        clock=FakeClock(now),
    )
    assert set(snap) == {"binance", "kraken"}  # dead venue dropped
    assert snap["binance"].mid == 100.1


def test_engine_emits_dislocation_and_layer_surfaces_it():
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    snap = synthetic_venue_snapshot("BTC/USDT", 30_000.0, now, ["binance", "kraken"],
                                    dislocation_bps=40.0, clock=FakeClock(now))
    ctx = build_context("BTC", now, {}, venue_snapshot=snap)
    eng = CrossExchangeEngine(obs_cfg(), FakeClock(now), reliability("cross_exchange"))
    evs = eng.observe(ctx)
    disl = [e for e in evs if e.name == "price_dislocation"]
    assert disl, "engine should emit price_dislocation for a 40bps gap"

    # the intelligence layer surfaces it into key_levels for the plugin
    bundle = EvidenceBundle(symbol="BTC", timestamp=now, evidences=disl)
    kl = IntelligenceLayer._key_levels(bundle)
    assert "dislocation" in kl
    assert kl["dislocation"]["buy_venue"] and kl["dislocation"]["sell_venue"]
    assert kl["dislocation"]["buy_venue"] != kl["dislocation"]["sell_venue"]


# ---- T-002 phantom-spread fixes ---------------------------------------------


TS = datetime(2026, 7, 16, tzinfo=timezone.utc)


def _top(bid: float, ask: float, ts: datetime = TS) -> VenueTop:
    return VenueTop(exchange="x", best_bid=bid, best_ask=ask, mid=(bid + ask) / 2.0, timestamp=ts)


def test_t002_ask_bid_overlap_produces_no_trade():
    # Wide 20 bps mid gap, but 10 bps spreads on each side overlap.
    snap = {"binance": _top(99.90, 100.10), "kraken": _top(100.00, 100.20)}
    assert compute_dislocation(snap) is None


def test_t002_genuine_executable_gap():
    snap = {"binance": _top(100.0, 100.2), "kraken": _top(100.6, 100.8)}
    bps, (cheap, rich) = compute_dislocation(snap)
    assert cheap == "binance" and rich == "kraken"
    assert bps == pytest.approx((100.6 - 100.2) / 100.4 * 10_000, abs=0.1)


def test_t002_stale_quote_dropped():
    fresh = TS
    stale = TS - timedelta(seconds=15)
    snap = {
        "binance": _top(100.0, 100.2, fresh),
        "kraken": _top(100.6, 100.8, stale),
    }
    assert compute_dislocation(snap, max_quote_age_seconds=10, now=TS) is None


def test_t002_only_one_fresh_venue_returns_none():
    stale = TS - timedelta(seconds=15)
    snap = {
        "binance": _top(100.0, 100.2, stale),
        "kraken": _top(100.6, 100.8, stale),
    }
    assert compute_dislocation(snap, max_quote_age_seconds=5, now=TS) is None


def test_t002_venue_skew_rejects_pair():
    t1 = TS
    t2 = TS - timedelta(seconds=3)
    snap = {
        "binance": _top(100.0, 100.2, t1),
        "kraken": _top(100.6, 100.8, t2),
    }
    assert compute_dislocation(snap, max_venue_skew_seconds=2, now=TS) is None


def test_t002_realistic_tight_books_no_trade():
    # 2 bps markets across 3 venues; after executable pricing there is no gap.
    snap = {
        "binance": _top(99.99, 100.01),
        "kraken": _top(99.98, 100.00),
        "coinbase": _top(100.00, 100.02),
    }
    assert compute_dislocation(snap) is None


def test_t002_synthetic_snapshot_still_fires():
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    snap = synthetic_venue_snapshot("BTC/USDT", 30_000.0, now, ["binance", "kraken"],
                                    dislocation_bps=40.0, spread_bps=1.0,
                                    clock=FakeClock(now))
    result = compute_dislocation(snap)
    assert result is not None
    assert result[0] > 35  # gross executable spread still ~38 bps after 1 bps spreads


def test_t002_mid_gap_with_wider_spreads_no_trade():
    # 30 bps mid gap, 35 bps spreads → the ask/bid overlap kills the arb.
    snap = {
        "binance": _top(99.825, 100.175),  # 35 bps spread around 100
        "kraken": _top(100.125, 100.475),  # 35 bps spread around 100.3 (30 bps mid gap)
    }
    assert compute_dislocation(snap) is None
