"""Clock abstraction (§4.5).

Every module obtains time via a ``Clock`` — NEVER ``datetime.utcnow()`` /
``datetime.now()`` directly (§0 rule 6). This single rule lets the identical
pipeline run live and in backtest, and is what makes replay byte-identical
(§13 test 7): in backtest the clock returns the simulator's candle time, so no
wall-clock leakage enters any decision.

All times are timezone-aware UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Anything that can report the current UTC time."""

    def now(self) -> datetime: ...


class LiveClock:
    """Wall-clock time, timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class BacktestClock:
    """Simulator-driven clock; the backtest engine ``set()``s the candle time.

    Starts unset and raises if queried before the first ``set()`` so that a
    backtest can never silently fall back to wall-clock time.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._t: datetime | None = None
        if start is not None:
            self.set(start)

    def set(self, t: datetime) -> None:
        if t.tzinfo is None:
            raise ValueError("BacktestClock requires timezone-aware UTC datetimes")
        self._t = t.astimezone(timezone.utc)

    def now(self) -> datetime:
        if self._t is None:
            raise RuntimeError("BacktestClock queried before set()")
        return self._t


__all__ = ["BacktestClock", "Clock", "LiveClock"]
