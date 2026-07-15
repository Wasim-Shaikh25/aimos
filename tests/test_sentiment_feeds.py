"""Sentiment feed tests (§4.4 — card P1-T4 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.schemas import Headline
from aimos.data.sentiment_feeds import HeadlineStore, parse_fear_greed, parse_rss_items

TS = datetime(2026, 7, 9, tzinfo=timezone.utc)
TS_MS = int(TS.timestamp() * 1000)


def test_parse_fear_greed_fixture():
    payload = {
        "data": [
            {"value": "40", "timestamp": "1700000000"},
            {"value": "72", "timestamp": "1700086400"},
        ]
    }
    out = parse_fear_greed(payload)
    assert len(out) == 2
    assert out[0][1] == 40
    assert out[1][1] == 72
    assert out[0][0].tzinfo is not None


def test_parse_fear_greed_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_fear_greed({"data": [{"value": "150", "timestamp": "1700000000"}]})


def test_headline_dedup_by_url_and_title():
    store = HeadlineStore()
    h1 = Headline(timestamp=TS, source="coindesk", title="ETF approved", url="http://x/1")
    h2 = Headline(timestamp=TS, source="coindesk", title="ETF approved", url="http://x/1")  # dup
    h3 = Headline(timestamp=TS, source="ct", title="ETF approved", url="http://x/2")  # diff url
    assert store.add(h1) is True
    assert store.add(h2) is False  # duplicate rejected
    assert store.add(h3) is True
    assert len(store) == 2


def test_headline_ingest_counts_new():
    store = HeadlineStore()
    items = parse_rss_items(
        [
            {"title": "A", "link": "http://x/a", "published_ms": TS_MS},
            {"title": "B", "link": "http://x/b", "published_ms": TS_MS},
            {"title": "A", "link": "http://x/a", "published_ms": TS_MS},  # dup
        ],
        source="coindesk",
    )
    assert store.ingest(items) == 2
    assert len(store) == 2
