"""Funding + whale (large-print) tests (§4.3, §5.8 — card P1-T3 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

from aimos.core.schemas import Direction
from aimos.data.funding import build_funding_frame
from aimos.data.whale import detect_large_prints, net_flow_usd

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
TS_MS = int(TS.timestamp() * 1000)


def test_build_funding_frame_merges_rate_and_oi():
    rates = [(TS_MS, 0.0001), (TS_MS + 3600_000, 0.0002)]
    ois = [(TS_MS, 1_000_000.0), (TS_MS + 3600_000, 1_100_000.0)]
    df = build_funding_frame(rates, ois)
    assert list(df.columns) == ["rate", "oi"]
    assert df.index.tz is not None
    assert df.iloc[0]["rate"] == 0.0001
    assert df.iloc[1]["oi"] == 1_100_000.0


def test_build_funding_frame_without_oi():
    df = build_funding_frame([(TS_MS, 0.0001)])
    assert "oi" in df.columns
    assert len(df) == 1


def test_detect_large_prints_threshold():
    trades = [
        {"timestamp": TS_MS, "price": 100.0, "amount": 3000.0, "side": "buy"},   # 300k
        {"timestamp": TS_MS, "price": 100.0, "amount": 100.0, "side": "sell"},   # 10k (below)
        {"timestamp": TS_MS, "price": 100.0, "amount": 5000.0, "side": "sell"},  # 500k
    ]
    prints = detect_large_prints(trades, "BTC", min_notional_usd=250_000)
    assert len(prints) == 2
    assert prints[0].side == Direction.BULLISH
    assert prints[1].side == Direction.BEARISH


def test_net_flow_windowed():
    prints = detect_large_prints(
        [
            {"timestamp": TS_MS, "price": 100.0, "amount": 3000.0, "side": "buy"},   # +300k
            {"timestamp": TS_MS, "price": 100.0, "amount": 5000.0, "side": "sell"},  # -500k
        ],
        "BTC",
        min_notional_usd=250_000,
    )
    now = datetime(2026, 7, 9, 12, 30, tzinfo=timezone.utc)
    net = net_flow_usd(prints, now=now, window_minutes=60)
    assert net == -200_000.0

    # window excludes the old prints
    later = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
    assert net_flow_usd(prints, now=later, window_minutes=60) == 0.0
