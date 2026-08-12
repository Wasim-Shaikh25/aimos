"""Cross-exchange + Correlation + Streams tests (§5.11-5.12, §21.3 — P2-T6/T7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from aimos.core.clock import LiveClock
from aimos.core.schemas import Direction, MarketContext, Timeframe, VenueTop
from aimos.data.streams import (
    Liquidation,
    RecordedStreamSource,
    StreamHealth,
    liquidation_cascade_evidence,
)
from aimos.observation.correlation import CorrelationEngine
from aimos.observation.cross_exchange import CrossExchangeEngine, compute_dislocation
from tests.conftest import make_candles, obs_cfg, reliability

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


# ---- cross-exchange ----

def test_dislocation_plain():
    snap = {
        "binance": VenueTop(exchange="binance", best_bid=99.9, best_ask=100.1, mid=100.0, timestamp=TS),
        "kraken": VenueTop(exchange="kraken", best_bid=100.4, best_ask=100.6, mid=100.5, timestamp=TS),
    }
    res = compute_dislocation(snap)
    assert res is not None
    bps, (cheap, rich) = res
    assert cheap == "binance" and rich == "kraken"
    # Executable spread: sell at kraken bid, buy at binance ask.
    assert bps == pytest.approx((100.4 - 100.1) / 100.25 * 10_000, abs=0.1)


def test_dislocation_depeg_adjusted():
    # Same nominal mid, but kraken quotes in a depegged USDC (0.95). After USD
    # conversion the real dislocation appears (§16.1 B-3).
    snap = {
        "binance": VenueTop(exchange="binance", best_bid=99.9, best_ask=100.1, mid=100.0, timestamp=TS),
        "kraken": VenueTop(exchange="kraken", best_bid=99.9, best_ask=100.1, mid=100.0, timestamp=TS),
    }
    res = compute_dislocation(
        snap,
        venue_quotes={"binance": "USDT", "kraken": "USDC"},
        stable_rates={"USDT": 1.0, "USDC": 0.95},
    )
    bps, (cheap, rich) = res
    assert cheap == "kraken"  # 100*0.95 = 95 USD is cheaper
    assert bps > 400  # ~5% dislocation once converted


def test_cross_exchange_engine_emits_dislocation():
    snap = {
        "binance": VenueTop(exchange="binance", best_bid=99.9, best_ask=100.1, mid=100.0, timestamp=TS),
        "kraken": VenueTop(exchange="kraken", best_bid=100.4, best_ask=100.6, mid=100.5, timestamp=TS),
    }
    eng = CrossExchangeEngine(obs_cfg(), LiveClock(), reliability("cross_exchange"))
    evs = eng.observe(MarketContext(symbol="BTC", now=TS, venue_snapshot=snap))
    assert [e for e in evs if e.name == "price_dislocation"]


# ---- correlation ----

def test_correlation_btc_beta_and_pull():
    rng = np.random.default_rng(0)
    n = 210
    btc_ret = rng.normal(0, 0.01, n)
    btc_ret[-1] = 0.10  # large final BTC move for btc_pull, kept consistent below
    btc_close = 100 * np.cumprod(1 + btc_ret)
    own_close = 100 * np.cumprod(1 + 2.0 * btc_ret)  # own_ret == 2·btc_ret → beta 2
    btc_df = make_candles(list(btc_close))
    own_df = make_candles(list(own_close))
    eng = CorrelationEngine(obs_cfg(), LiveClock(), reliability("correlation"))
    ctx = MarketContext(symbol="ALT", now=own_df.index[-1].to_pydatetime(),
                        candles={Timeframe.H1: own_df}, peers={"BTC": btc_df})
    evs = eng.observe(ctx)
    names = {e.name for e in evs}
    assert "btc_beta" in names
    beta_ev = [e for e in evs if e.name == "btc_beta"][0]
    assert beta_ev.meta["beta"] == pytest.approx(2.0, abs=0.2)
    assert "btc_pull" in names


# ---- streams ----

def test_recorded_stream_replay_deterministic():
    events = [{"type": "trade", "ts": i} for i in range(5)]
    src = RecordedStreamSource(events)
    a = list(src.events())
    b = list(RecordedStreamSource(events).events())
    assert a == b == events


def test_stream_health_degrade():
    h = StreamHealth(unhealthy_after_seconds=10)
    h.mark("btc_book", TS)
    assert h.is_healthy("btc_book", TS + timedelta(seconds=5))
    assert not h.is_healthy("btc_book", TS + timedelta(seconds=15))
    assert h.should_degrade("btc_book", TS + timedelta(seconds=15))
    assert h.should_degrade("unknown_stream", TS)  # never seen → degrade


def test_liquidation_cascade_evidence():
    # baseline small liquidations, then a big cluster of long liquidations
    liqs = [Liquidation(TS - timedelta(minutes=60 - i), Direction.BEARISH, 10_000) for i in range(50)]
    liqs += [Liquidation(TS - timedelta(minutes=2), Direction.BULLISH, 5_000_000)]  # longs liquidated
    ev = liquidation_cascade_evidence(
        liqs, "BTC", TS, window_minutes=5, hist_window=288, reliability=0.5, z_cap=3.0
    )
    assert ev is not None
    assert ev.name == "liquidation_cascade"
    assert ev.direction == Direction.BULLISH  # longs liquidated → fade up
    assert ev.meta.get("scalp_gate") is True
