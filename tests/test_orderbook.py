"""Order-book aggregation tests (§4.2 — card P1-T3 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aimos.data.orderbook import BookWindow, aggregate_book

TS = datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_aggregate_math_hand_computed():
    # mid = 100.05; within 0.5% → [99.5, 100.55]
    bids = [[100.0, 2.0], [99.0, 5.0]]  # 99.0 is inside band (>=99.5? no) → excluded
    asks = [[100.1, 3.0], [101.0, 4.0]]  # 101.0 outside band → excluded
    agg = aggregate_book(TS, bids, asks, book_depth_pct=0.5)

    assert agg.best_bid == 100.0
    assert agg.best_ask == 100.1
    mid = 100.05
    assert agg.spread_bps == pytest.approx((100.1 - 100.0) / mid * 10_000)
    # only 100.0 bid (>=99.5) counts; 99.0 excluded
    assert agg.bid_depth_usd == pytest.approx(100.0 * 2.0)
    # only 100.1 ask (<=100.55) counts; 101.0 excluded
    assert agg.ask_depth_usd == pytest.approx(100.1 * 3.0)
    exp_imb = (200.0 - 300.3) / (200.0 + 300.3)
    assert agg.imbalance == pytest.approx(exp_imb)


def test_empty_side_raises():
    with pytest.raises(ValueError):
        aggregate_book(TS, [], [[100.1, 1.0]], book_depth_pct=0.5)


@given(
    bid_px=st.floats(min_value=1.0, max_value=1e6),
    ask_add=st.floats(min_value=0.01, max_value=1000.0),
    bid_sz=st.floats(min_value=0.0, max_value=1e6),
    ask_sz=st.floats(min_value=0.0, max_value=1e6),
)
def test_imbalance_always_in_bounds(bid_px, ask_add, bid_sz, ask_sz):
    asks = [[bid_px + ask_add, ask_sz]]
    bids = [[bid_px, bid_sz]]
    agg = aggregate_book(TS, bids, asks, book_depth_pct=100.0)  # wide band
    assert -1.0 <= agg.imbalance <= 1.0


def test_book_window_rolls_and_means():
    w = BookWindow(maxlen=3)
    for imb in (0.2, 0.4, 0.6, 0.8):
        w.add(aggregate_book(TS, [[100.0, imb + 1]], [[100.1, 1.0]], 100.0))
    assert len(w) == 3  # rolled, oldest dropped
    assert w.mean_imbalance(3) == pytest.approx(
        sum(a.imbalance for a in w.snapshots()) / 3
    )
