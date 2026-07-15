"""Rate-limit budgeter tests (§23.2 — card P1-T1 DoD)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aimos.data.ratelimit import RateLimitBudgeter, TokenBucket
from tests.conftest import FakeClock

PRIORITY = ["orders", "position", "orderbook", "candles", "discovery"]


def _budgeter(clock: FakeClock) -> RateLimitBudgeter:
    return RateLimitBudgeter(
        clock=clock,
        priority_classes=PRIORITY,
        utilization_ceiling=0.70,
        ceiling_halve_hours=1.0,
        window_seconds=60.0,
    )


def test_token_bucket_refills_over_window():
    clock = FakeClock()
    b = TokenBucket(capacity=60, window=timedelta(seconds=60), clock=clock)
    assert b.try_consume(60)
    assert not b.try_consume(1)  # empty
    clock.advance(30)  # half window → ~30 tokens
    assert b.available() >= 29
    assert b.try_consume(20)


def test_ceiling_is_70_percent_of_published():
    clock = FakeClock()
    b = _budgeter(clock)
    b.register_limit("binance", "candles", published_limit=100)
    # 100 × 0.70 = 70 effective capacity
    assert b._buckets[("binance", "candles")].capacity == 70


def test_bucket_exhaustion_queues_low_priority():
    clock = FakeClock()
    b = _budgeter(clock)
    b.register_limit("binance", "candles", published_limit=3)  # cap 2.1
    assert b.acquire("binance", "candles") is True
    assert b.acquire("binance", "candles") is True
    # third exhausts the bucket → queued, not granted
    assert b.acquire("binance", "candles") is False
    assert b.queue_depth("binance") == 1
    assert b.metrics.queued == 1


def test_order_class_preempts_candle_class():
    clock = FakeClock()
    b = _budgeter(clock)
    b.register_limit("binance", "orders", published_limit=2)  # cap 1.4 → 0.4 after 1 grant
    b.register_limit("binance", "candles", published_limit=100)  # plenty

    assert b.acquire("binance", "orders") is True  # consumes the single order token
    # order bucket empty → next order queued (highest priority at head)
    assert b.acquire("binance", "orders") is False
    # a candle now has tokens, but a higher-priority order is queued ahead → it
    # must wait behind the order (preemption, no downward queue-jumping)
    assert b.acquire("binance", "candles") is False
    assert b.queue_depth("binance") == 2

    clock.advance(120)  # refill the order bucket
    granted = b.drain("binance")
    assert granted[0] == "orders"  # order released before candle
    assert "candles" in granted


def test_429_halves_ceiling_and_restores():
    clock = FakeClock(datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc))
    b = _budgeter(clock)
    b.register_limit("binance", "candles", published_limit=100)
    bucket = b._buckets[("binance", "candles")]
    assert bucket.capacity == 70

    backoff = b.note_throttle("binance", retry_after_seconds=5)
    assert backoff == 5
    assert bucket.capacity == 35  # halved
    assert b.metrics.throttled == 1
    assert b.is_backing_off("binance") is True

    clock.advance(10)  # past backoff window
    assert b.is_backing_off("binance") is False

    clock.advance(3600)  # past the 1h halving window
    b.acquire("binance", "candles")  # triggers restore check
    assert bucket.capacity == 70  # ceiling restored


def test_backoff_blocks_grants():
    clock = FakeClock()
    b = _budgeter(clock)
    b.register_limit("kraken", "candles", published_limit=100)
    b.note_throttle("kraken", retry_after_seconds=30)
    # even with tokens available, a backing-off venue grants nothing
    assert b.acquire("kraken", "candles") is False
    clock.advance(31)
    assert b.acquire("kraken", "candles") is True
