# GPL-3.0 origin: freqtrade/freqtrade:freqtrade/plugins/protections/ — REWRITE BEFORE ANY DISTRIBUTION
# Listed in vendor/GPL_TRIPWIRE.md (§21.1, §22.2C). AIMOS is PRIVATE/non-distributed,
# so GPL obligations do not currently trigger; any future distribution (sale,
# sharing, service, open-source) requires clean-room rewriting this file first.
# This is a concept reimplementation from the §21.1 spec, adapted to read our
# journal instead of freqtrade's DB.
"""Protections — stateful guards that lock trading after bad patterns (§21.1).

Small guards over the journal. This reference ships StoplossGuard; the rest
(SymbolCooldown, LowProfitSymbol, MaxDrawdownGuard) follow the same shape and
are filled in at Phase 4 (card P4-T3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence


@dataclass(frozen=True)
class Lock:
    scope: str  # "global" or a symbol
    until: datetime
    reason: str


class StoplossGuard:
    """≥ ``trigger_count`` stop-losses across the book within ``lookback`` →
    a global trade lock for ``lock`` hours (§21.1)."""

    def __init__(self, trigger_count: int, lookback_hours: float, lock_hours: float) -> None:
        self.trigger_count = trigger_count
        self.lookback = timedelta(hours=lookback_hours)
        self.lock = timedelta(hours=lock_hours)

    def evaluate(self, stop_loss_times: Sequence[datetime], now: datetime) -> Lock | None:
        recent = [t for t in stop_loss_times if now - t <= self.lookback]
        if len(recent) >= self.trigger_count:
            return Lock(scope="global", until=now + self.lock, reason="stoploss_guard")
        return None


__all__ = ["Lock", "StoplossGuard"]
