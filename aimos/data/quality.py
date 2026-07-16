"""Data quality gate + clock discipline (§23.3, card P1-T5).

Sits between fetch and store, before any engine sees data:

* **Bad-tick quarantine** — a price deviating > ``bad_tick_atr_mult`` × ATR from
  the last valid value AND unconfirmed by a second venue within a tolerance is
  quarantined (stored flagged, excluded from engines).
* **Cross-venue sanity** — primary mid deviating > ``cross_venue_max_deviation_pct``
  from the median of others marks the venue degraded (switch to secondary feed).
* **Staleness** — a feed older than ``staleness_cadence_mult`` × its cadence
  blocks NEW entries on that symbol (managing existing positions continues).
* **Clock discipline** — NTP drift thresholds map to warn / pause-new-entries.

Pure decision functions; the runtime wires them to the event bus and store.
Time is passed in explicitly (§4.5) — no wall-clock reads here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from statistics import median
from typing import Sequence


class VenueStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"


class DriftStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    PAUSE = "pause"


@dataclass(frozen=True)
class TickCheck:
    quarantined: bool
    reason: str


def check_bad_tick(
    price: float,
    last_valid_price: float,
    atr: float,
    bad_tick_atr_mult: float,
    second_venue_price: float | None = None,
    second_venue_tolerance_pct: float = 0.5,
) -> TickCheck:
    """Quarantine a glitch print (§23.3).

    A tick is a bad tick when it deviates more than ``mult × ATR`` from the last
    valid price AND is NOT confirmed by a second venue (within tolerance). A
    second venue showing the same move means the move is real → not quarantined.
    """
    if atr <= 0:
        return TickCheck(False, "no atr reference")
    deviation = abs(price - last_valid_price)
    threshold = bad_tick_atr_mult * atr
    if deviation <= threshold:
        return TickCheck(False, "within atr band")
    if second_venue_price is not None:
        tol = second_venue_tolerance_pct / 100.0
        if abs(price - second_venue_price) <= abs(price) * tol:
            return TickCheck(False, "confirmed by second venue")
    return TickCheck(True, f"deviation {deviation:.4g} > {bad_tick_atr_mult}×ATR ({threshold:.4g})")


def check_cross_venue(
    primary_mid: float,
    other_mids: Sequence[float],
    max_deviation_pct: float,
) -> VenueStatus:
    """Mark the primary venue degraded if it dislocates from the peer median (§23.3)."""
    if not other_mids:
        return VenueStatus.OK
    ref = median(other_mids)
    if ref <= 0:
        return VenueStatus.OK
    dev_pct = abs(primary_mid - ref) / ref * 100.0
    return VenueStatus.DEGRADED if dev_pct > max_deviation_pct else VenueStatus.OK


def is_stale(
    last_update: datetime,
    now: datetime,
    cadence: timedelta,
    staleness_cadence_mult: float,
) -> bool:
    """True if a feed is older than ``mult × cadence`` → blocks new entries (§23.3)."""
    age = now - last_update
    return age.total_seconds() > cadence.total_seconds() * staleness_cadence_mult


def clock_drift_status(drift_ms: float, warn_ms: float, pause_ms: float) -> DriftStatus:
    """Map NTP drift to a discipline status (§23.3 clock discipline)."""
    d = abs(drift_ms)
    if d >= pause_ms:
        return DriftStatus.PAUSE
    if d >= warn_ms:
        return DriftStatus.WARN
    return DriftStatus.OK


__all__ = [
    "DriftStatus",
    "TickCheck",
    "VenueStatus",
    "check_bad_tick",
    "check_cross_venue",
    "clock_drift_status",
    "is_stale",
]
