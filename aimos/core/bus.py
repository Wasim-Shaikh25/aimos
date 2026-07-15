"""In-process event bus (§25.8).

Simple synchronous pub/sub with a fixed ``Topic`` enum. Publishing is
fire-and-forget with a per-subscriber ``try/except``: one raising subscriber
must never break publication for the others, and must never propagate up into
the pipeline tick (§10.1 graceful degradation). Subscriber exceptions are
logged via structlog and swallowed.

This is deliberately not asyncio-based: publishers may be sync or async, and a
synchronous fan-out keeps ordering deterministic for replay tests.
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)

Subscriber = Callable[["Topic", Any], None]


class Topic(str, Enum):
    """Canonical event topics (§25.8)."""

    DECISION = "decision"
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    MANAGEMENT_EVENT = "management_event"
    REGIME_CHANGE = "regime_change"
    TIER_CHANGE = "tier_change"
    RISK_ALERT = "risk_alert"
    VENUE_STATUS = "venue_status"
    AGENT_EVENT = "agent_event"
    SYSTEM_HEALTH = "system_health"


class EventBus:
    """Synchronous in-process pub/sub keyed by ``Topic``."""

    def __init__(self) -> None:
        self._subs: dict[Topic, list[Subscriber]] = defaultdict(list)

    def subscribe(self, topic: Topic, fn: Subscriber) -> None:
        self._subs[topic].append(fn)

    def unsubscribe(self, topic: Topic, fn: Subscriber) -> None:
        if fn in self._subs[topic]:
            self._subs[topic].remove(fn)

    def publish(self, topic: Topic, payload: Any) -> None:
        """Fire-and-forget. A raising subscriber is logged and skipped."""
        for fn in list(self._subs[topic]):
            try:
                fn(topic, payload)
            except Exception:  # noqa: BLE001 — isolation is the point (§25.8)
                log.exception("bus_subscriber_failed", topic=topic.value)

    def subscriber_count(self, topic: Topic) -> int:
        return len(self._subs[topic])


__all__ = ["EventBus", "Subscriber", "Topic"]
