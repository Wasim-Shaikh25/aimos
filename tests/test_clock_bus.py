"""Clock + event bus tests (§4.5, §25.8 — card P0-T5 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.bus import EventBus, Topic
from aimos.core.clock import BacktestClock, Clock, LiveClock


def test_live_clock_is_utc_aware():
    t = LiveClock().now()
    assert t.tzinfo is not None
    assert t.utcoffset() == timezone.utc.utcoffset(None) or t.tzinfo == timezone.utc


def test_backtest_clock_injection():
    c = BacktestClock()
    t = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)
    c.set(t)
    assert c.now() == t
    # advancing the sim moves the clock deterministically
    t2 = datetime(2026, 7, 9, 14, 40, tzinfo=timezone.utc)
    c.set(t2)
    assert c.now() == t2


def test_backtest_clock_requires_aware_datetime():
    with pytest.raises(ValueError):
        BacktestClock().set(datetime(2026, 7, 9, 14, 35))  # naive


def test_backtest_clock_unset_raises():
    with pytest.raises(RuntimeError):
        BacktestClock().now()


def test_clocks_satisfy_protocol():
    assert isinstance(LiveClock(), Clock)
    assert isinstance(BacktestClock(datetime(2026, 1, 1, tzinfo=timezone.utc)), Clock)


def test_raising_subscriber_does_not_break_publish():
    bus = EventBus()
    received: list = []

    def boom(topic, payload):
        raise RuntimeError("subscriber failure")

    def good(topic, payload):
        received.append(payload)

    bus.subscribe(Topic.DECISION, boom)
    bus.subscribe(Topic.DECISION, good)

    bus.publish(Topic.DECISION, {"x": 1})  # must not raise

    assert received == [{"x": 1}]


def test_topics_isolated():
    bus = EventBus()
    hits: list = []
    bus.subscribe(Topic.TRADE_OPENED, lambda t, p: hits.append(p))
    bus.publish(Topic.TRADE_CLOSED, "nope")
    assert hits == []
    bus.publish(Topic.TRADE_OPENED, "yes")
    assert hits == ["yes"]


def test_unsubscribe():
    bus = EventBus()
    hits: list = []
    fn = lambda t, p: hits.append(p)  # noqa: E731
    bus.subscribe(Topic.RISK_ALERT, fn)
    bus.unsubscribe(Topic.RISK_ALERT, fn)
    bus.publish(Topic.RISK_ALERT, "x")
    assert hits == []
