"""Central rate-limit budgeter (§23.2, card P1-T1).

ALL REST calls route through this. Per (exchange, weight-class) token buckets
initialised from each exchange's published limits at a 70% utilization ceiling.
Priority classes preempt: orders > position/balance > orderbook > candles >
discovery — a high-priority acquire jumps ahead of queued low-priority work.

On HTTP 429/418: exponential backoff and the venue's ceiling is halved for one
hour, restored afterwards. Metrics counters expose grants/queues/throttles for
the dashboard health matrix (§23.5).

Time is injected via a ``Clock`` (§4.5) so bucket refills and cooldowns are
deterministic in tests and backtests — no wall-clock reads here.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from aimos.core.clock import Clock

log = structlog.get_logger(__name__)


@dataclass
class BudgeterMetrics:
    """Counters exposed at /metrics (§23.5)."""

    granted: int = 0
    queued: int = 0
    throttled: int = 0  # 429/418 events
    denied: int = 0  # could not satisfy even after refill


@dataclass(order=True)
class _PendingRequest:
    # ordered by (priority_rank, seq) so lower rank = higher priority, FIFO ties
    priority_rank: int
    seq: int
    cost: int = field(compare=False)
    weight_class: str = field(compare=False)


class TokenBucket:
    """A refilling token bucket for one (exchange, weight-class).

    ``capacity`` is the effective per-window budget (published limit ×
    utilization ceiling). Tokens refill linearly across ``window``.
    """

    def __init__(self, capacity: float, window: timedelta, clock: Clock) -> None:
        self._base_capacity = float(capacity)
        self._capacity = float(capacity)
        self._window = window
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock.now()

    @property
    def capacity(self) -> float:
        return self._capacity

    def set_ceiling_fraction(self, fraction: float) -> None:
        """Scale effective capacity (used by 429 halving / restore)."""
        self._capacity = self._base_capacity * fraction
        self._tokens = min(self._tokens, self._capacity)

    def _refill(self) -> None:
        now = self._clock.now()
        elapsed = (now - self._last).total_seconds()
        if elapsed <= 0:
            return
        rate = self._capacity / self._window.total_seconds()
        self._tokens = min(self._capacity, self._tokens + elapsed * rate)
        self._last = now

    def available(self) -> float:
        self._refill()
        return self._tokens

    def try_consume(self, cost: float) -> bool:
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False


class RateLimitBudgeter:
    """Per-exchange budgeter with priority queueing and 429 handling."""

    def __init__(
        self,
        clock: Clock,
        priority_classes: Iterable[str],
        utilization_ceiling: float = 0.70,
        ceiling_halve_hours: float = 1.0,
        window_seconds: float = 60.0,
    ) -> None:
        self._clock = clock
        self._ceiling = utilization_ceiling
        self._halve_hours = ceiling_halve_hours
        self._window = timedelta(seconds=window_seconds)
        # priority rank: earlier in the list = higher priority = lower rank
        self._rank = {name: i for i, name in enumerate(priority_classes)}
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._queues: dict[str, list[_PendingRequest]] = {}
        self._throttled_until: dict[str, datetime | None] = {}
        self._halved_until: dict[str, datetime | None] = {}
        self._seq = itertools.count()
        self.metrics = BudgeterMetrics()

    # -- setup ---------------------------------------------------------------

    def register_limit(self, exchange: str, weight_class: str, published_limit: float) -> None:
        """Register a weight-class with its published per-window limit."""
        cap = published_limit * self._ceiling
        self._buckets[(exchange, weight_class)] = TokenBucket(cap, self._window, self._clock)
        self._queues.setdefault(exchange, [])

    def _rank_of(self, weight_class: str) -> int:
        # unknown classes are lowest priority
        return self._rank.get(weight_class, len(self._rank))

    # -- 429 / 418 handling --------------------------------------------------

    def note_throttle(self, exchange: str, retry_after_seconds: float | None = None) -> float:
        """Record a 429/418: halve ceiling for an hour, return backoff seconds."""
        self.metrics.throttled += 1
        now = self._clock.now()
        self._halved_until[exchange] = now + timedelta(hours=self._halve_hours)
        for (ex, _wc), bucket in self._buckets.items():
            if ex == exchange:
                bucket.set_ceiling_fraction(0.5)
        backoff = retry_after_seconds if retry_after_seconds is not None else 1.0
        self._throttled_until[exchange] = now + timedelta(seconds=backoff)
        log.warning("rate_limit_throttled", exchange=exchange, backoff_s=backoff)
        return backoff

    def _maybe_restore_ceiling(self, exchange: str) -> None:
        until = self._halved_until.get(exchange)
        if until is not None and self._clock.now() >= until:
            self._halved_until[exchange] = None
            for (ex, _wc), bucket in self._buckets.items():
                if ex == exchange:
                    bucket.set_ceiling_fraction(1.0)
            log.info("rate_limit_ceiling_restored", exchange=exchange)

    def is_backing_off(self, exchange: str) -> bool:
        until = self._throttled_until.get(exchange)
        return until is not None and self._clock.now() < until

    # -- acquire -------------------------------------------------------------

    def acquire(self, exchange: str, weight_class: str, cost: int = 1) -> bool:
        """Try to acquire ``cost`` tokens NOW.

        Returns True if granted immediately. If not, the request is enqueued in
        the exchange's priority queue and False is returned; call
        ``drain(exchange)`` after a refill/higher-priority completion to release
        newly grantable work in priority order.
        """
        self._maybe_restore_ceiling(exchange)
        bucket = self._buckets.get((exchange, weight_class))
        if bucket is None:
            raise KeyError(f"no bucket registered for {exchange}/{weight_class}")

        # If higher-priority work is already queued, a lower-priority request
        # must wait behind it (preemption / no queue-jumping downward).
        queue = self._queues[exchange]
        my_rank = self._rank_of(weight_class)
        head_rank = queue[0].priority_rank if queue else None
        blocked_by_priority = head_rank is not None and head_rank < my_rank

        if not blocked_by_priority and not self.is_backing_off(exchange) and bucket.try_consume(cost):
            self.metrics.granted += 1
            return True

        heapq.heappush(
            queue,
            _PendingRequest(my_rank, next(self._seq), cost, weight_class),
        )
        self.metrics.queued += 1
        return False

    def drain(self, exchange: str) -> list[str]:
        """Release now-grantable queued requests in priority order.

        Returns the weight-classes granted, most-important first.
        """
        self._maybe_restore_ceiling(exchange)
        if self.is_backing_off(exchange):
            return []
        queue = self._queues.get(exchange, [])
        granted: list[str] = []
        while queue:
            req = queue[0]
            bucket = self._buckets[(exchange, req.weight_class)]
            if bucket.try_consume(req.cost):
                heapq.heappop(queue)
                self.metrics.granted += 1
                granted.append(req.weight_class)
            else:
                break  # head can't be served → nothing lower-priority jumps it
        return granted

    def queue_depth(self, exchange: str) -> int:
        return len(self._queues.get(exchange, []))


__all__ = ["BudgeterMetrics", "RateLimitBudgeter", "TokenBucket"]
