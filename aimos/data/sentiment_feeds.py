"""Sentiment feeds — Fear & Greed + RSS headlines (§4.4, card P1-T4).

Phase 1 is free / no-keys: the alternative.me Fear & Greed index and RSS news
from CoinDesk/CoinTelegraph. Parsing is separated from fetching so tests run on
fixtures with no network. Headlines are deduped by (url, title) hash and kept in
a ``HeadlineStore``. Sentiment SCORING (lexicon) lives in the sentiment engine
(§5.10), not here — this module only ingests.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

from aimos.core.schemas import Headline


def parse_fear_greed(payload: dict) -> list[tuple[datetime, int]]:
    """Parse an alternative.me F&G response into (timestamp, value 0-100).

    Shape: ``{"data": [{"value": "40", "timestamp": "1700000000"}, ...]}``.
    """
    out: list[tuple[datetime, int]] = []
    for row in payload.get("data", []):
        value = int(row["value"])
        if not 0 <= value <= 100:
            raise ValueError(f"F&G value out of range: {value}")
        ts = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc)
        out.append((ts, value))
    return out


def _dedup_key(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}\x00{title}".encode("utf-8")).hexdigest()


class HeadlineStore:
    """De-duplicating headline store keyed by (url, title) (§4.4)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._items: list[Headline] = []

    def add(self, headline: Headline) -> bool:
        """Add a headline; returns True if new, False if a duplicate."""
        key = _dedup_key(headline.url, headline.title)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._items.append(headline)
        return True

    def ingest(self, headlines: Iterable[Headline]) -> int:
        """Add many; returns the count of newly-stored (non-duplicate) items."""
        return sum(1 for h in headlines if self.add(h))

    def recent(self, since: datetime) -> list[Headline]:
        return [h for h in self._items if h.timestamp >= since]

    def __len__(self) -> int:
        return len(self._items)


def parse_rss_items(items: Iterable[dict], source: str) -> list[Headline]:
    """Turn parsed RSS entries into ``Headline`` records (§4.4).

    Each item: ``{"title": str, "link": str, "published_ms": int}``.
    """
    out: list[Headline] = []
    for it in items:
        ts = datetime.fromtimestamp(int(it["published_ms"]) / 1000.0, tz=timezone.utc)
        out.append(
            Headline(timestamp=ts, source=source, title=it["title"], url=it["link"])
        )
    return out


__all__ = ["HeadlineStore", "parse_fear_greed", "parse_rss_items"]
