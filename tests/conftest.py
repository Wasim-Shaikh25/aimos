"""Shared test fixtures/helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class FakeClock:
    """Manually-advanced UTC clock for deterministic time-based tests (§4.5)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)

    def set(self, t: datetime) -> None:
        self._t = t
