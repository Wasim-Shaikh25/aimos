from datetime import datetime, timedelta, timezone

from aimos.core.schemas import BookAggregate, LargePrint, MarketContext
from aimos.data.context import build_context
from aimos.data.stream_feed import StreamFeed, book_from_depth, large_print_from_trade
from aimos.data.streaming import StreamEvent


def _ts() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_book_from_depth_computes_best_bid_ask_and_depth():
    ev = StreamEvent(
        type="book",
        timestamp=_ts(),
        venue="binance",
        symbol="BTC/USDT",
        data={
            "bids": [[69_900.0, 1.0], [69_800.0, 2.0]],
            "asks": [[70_100.0, 1.0], [70_200.0, 2.0]],
        },
    )
    book = book_from_depth(ev)
    assert isinstance(book, BookAggregate)
    assert book.best_bid == 69_900.0
    assert book.best_ask == 70_100.0
    assert book.spread_bps > 0
    assert book.bid_depth_usd > 0
    assert book.ask_depth_usd > 0
    assert -1.0 <= book.imbalance <= 1.0


def test_large_print_from_trade_maps_buyer_is_maker():
    buy = StreamEvent(
        type="trade",
        timestamp=_ts(),
        venue="binance",
        symbol="BTC/USDT",
        data={"price": 70_000.0, "qty": 0.5, "buyer_is_maker": False},
    )
    lp = large_print_from_trade(buy)
    assert lp.side.value == "bullish"
    assert lp.notional_usd == 35_000.0

    sell = StreamEvent(
        type="trade",
        timestamp=_ts(),
        venue="binance",
        symbol="BTC/USDT",
        data={"price": 70_000.0, "qty": 0.5, "buyer_is_maker": True},
    )
    lp = large_print_from_trade(sell)
    assert lp.side.value == "bearish"


def test_stream_feed_returns_snapshot_and_filters_stale_book():
    now = _ts()
    feed = StreamFeed(book_window_minutes=1.0, trade_window_minutes=5.0, min_notional_usd=10.0)
    feed.handle(StreamEvent(
        type="book", timestamp=now, venue="binance", symbol="BTC/USDT",
        data={"bids": [[69_900.0, 1.0]], "asks": [[70_100.0, 1.0]]},
    ))
    feed.handle(StreamEvent(
        type="trade", timestamp=now, venue="binance", symbol="BTC/USDT",
        data={"price": 70_000.0, "qty": 1.0, "buyer_is_maker": False},
    ))
    snap = feed.snapshot("BTC", now)
    assert len(snap["orderbook_window"]) == 1
    assert len(snap["trades_large"]) == 1

    stale = now + timedelta(minutes=2)
    snap = feed.snapshot("BTC", stale)
    assert snap["orderbook_window"] == []
    assert len(snap["trades_large"]) == 1


def test_stream_feed_builds_market_context():
    now = _ts()
    feed = StreamFeed(min_notional_usd=0.0)
    feed.handle(StreamEvent(
        type="book", timestamp=now, venue="binance", symbol="BTC/USDT",
        data={"bids": [[69_900.0, 1.0]], "asks": [[70_100.0, 1.0]]},
    ))
    feed.handle(StreamEvent(
        type="trade", timestamp=now, venue="binance", symbol="BTC/USDT",
        data={"price": 70_000.0, "qty": 1.0, "buyer_is_maker": False},
    ))
    import pandas as pd
    idx = pd.DatetimeIndex([now])
    candles = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=idx,
    )
    ctx = build_context(
        "BTC", now, {"1h": candles},
        **feed.snapshot("BTC", now),
    )
    assert isinstance(ctx, MarketContext)
    assert len(ctx.orderbook_window) == 1
    assert len(ctx.trades_large) == 1
