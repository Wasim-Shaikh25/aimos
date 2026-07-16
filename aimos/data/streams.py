"""Streaming market-data layer (§21.3, §17.2, card P2-T7).

Wraps cryptofeed (later) behind a swappable ``StreamSource`` protocol: L2 book
deltas, trades, funding, and liquidation feeds. Adds a new evidence
``liquidation_cascade`` (rolling liquidation-notional z-score, direction opposite
the liquidated side) and stream-health tracking that auto-degrades scalping when
a stream goes silent (§17.2 rule 3).

Deterministic replay: ``RecordedStreamSource`` yields recorded events in order so
replays produce identical evidence (§13 test 7). cryptofeed is an optional dep;
nothing here imports it — the concrete adapter lands with the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Iterator, Protocol, Sequence

from aimos.core.indicators import zscore_last
from aimos.core.schemas import Direction, Evidence, Timeframe


@dataclass(frozen=True)
class Liquidation:
    timestamp: datetime
    side: Direction  # side that was LIQUIDATED (BULLISH = longs liquidated)
    notional_usd: float


class StreamSource(Protocol):
    """A normalized multi-exchange stream (cryptofeed shape)."""

    def events(self) -> Iterator[dict]:
        """Yield normalized events: {type, timestamp, ...}."""
        ...


class RecordedStreamSource:
    """Deterministic replay source over a recorded event list (§13)."""

    def __init__(self, recorded: Sequence[dict]) -> None:
        self._recorded = list(recorded)

    def events(self) -> Iterator[dict]:
        yield from self._recorded


@dataclass
class StreamHealth:
    """Tracks last-message time per stream; flags degrade after silence (§17.2)."""

    unhealthy_after_seconds: float
    _last: dict[str, datetime] = field(default_factory=dict)

    def mark(self, stream: str, ts: datetime) -> None:
        self._last[stream] = ts

    def is_healthy(self, stream: str, now: datetime) -> bool:
        last = self._last.get(stream)
        if last is None:
            return False
        return (now - last) <= timedelta(seconds=self.unhealthy_after_seconds)

    def should_degrade(self, stream: str, now: datetime) -> bool:
        """True when the stream is unhealthy → scalping/T1 stream engines degrade."""
        return not self.is_healthy(stream, now)


def liquidation_cascade_evidence(
    liquidations: Sequence[Liquidation],
    symbol: str,
    now: datetime,
    window_minutes: int,
    hist_window: int,
    reliability: float,
    z_cap: float,
) -> Evidence | None:
    """Rolling liquidation-notional z-score → contrarian evidence (§21.3).

    Buckets recent liquidation notional; a spike z above the baseline fades the
    liquidated side (longs liquidated → bullish reversal evidence). Returns None
    when there is no cascade. meta gates scalping during cascades.
    """
    if len(liquidations) < 2:
        return None
    cutoff = now - timedelta(minutes=window_minutes)
    recent = [x for x in liquidations if x.timestamp >= cutoff]
    if not recent:
        return None
    # baseline: per-event notional series over the provided history
    notionals = [x.notional_usd for x in liquidations][-hist_window:]
    window_notional = sum(x.notional_usd for x in recent)
    series = notionals + [window_notional]
    import numpy as np

    z = zscore_last(np.asarray(series, dtype=float))
    if z <= 0:
        return None
    # net liquidated side over the window
    net = sum(
        x.notional_usd if x.side == Direction.BULLISH else -x.notional_usd for x in recent
    )
    if net == 0:
        return None
    # longs liquidated (net>0, BULLISH side liquidated) → fade up = bullish reversal
    direction = Direction.BULLISH if net > 0 else Direction.BEARISH
    strength = min(abs(z) / z_cap, 1.0) if z_cap > 0 else 0.0
    return Evidence(
        source="streams.liquidation_cascade", symbol=symbol, timeframe=Timeframe.M5,
        timestamp=now, name="liquidation_cascade", value=float(z), direction=direction,
        strength=strength, reliability=reliability,
        meta={"window_notional": float(window_notional), "cascade": True, "scalp_gate": True},
    )


__all__ = [
    "Liquidation",
    "RecordedStreamSource",
    "StreamHealth",
    "StreamSource",
    "liquidation_cascade_evidence",
]
