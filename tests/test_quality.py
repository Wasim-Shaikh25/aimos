"""Data quality gate + clock discipline tests (§23.3 — card P1-T5 DoD)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aimos.data.quality import (
    DriftStatus,
    VenueStatus,
    check_bad_tick,
    check_cross_venue,
    clock_drift_status,
    is_stale,
)

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def test_glitch_print_quarantined():
    # last valid 100, ATR 1 → band ±8. A 150 print with no second-venue confirm.
    r = check_bad_tick(price=150.0, last_valid_price=100.0, atr=1.0, bad_tick_atr_mult=8.0)
    assert r.quarantined is True


def test_real_move_confirmed_by_second_venue_not_quarantined():
    r = check_bad_tick(
        price=150.0, last_valid_price=100.0, atr=1.0, bad_tick_atr_mult=8.0,
        second_venue_price=150.2, second_venue_tolerance_pct=0.5,
    )
    assert r.quarantined is False


def test_within_band_not_quarantined():
    r = check_bad_tick(price=105.0, last_valid_price=100.0, atr=1.0, bad_tick_atr_mult=8.0)
    assert r.quarantined is False


def test_cross_venue_degraded_switch_flag():
    # primary 3.5% away from peer median (100) → degraded
    assert check_cross_venue(103.5, [100.0, 100.2, 99.8], max_deviation_pct=3.0) is VenueStatus.DEGRADED
    assert check_cross_venue(101.0, [100.0, 100.2, 99.8], max_deviation_pct=3.0) is VenueStatus.OK


def test_staleness_blocks_new_entries():
    cadence = timedelta(seconds=10)  # book poll cadence (§4.2)
    fresh = TS - timedelta(seconds=15)
    stale = TS - timedelta(seconds=25)
    assert is_stale(fresh, TS, cadence, staleness_cadence_mult=2.0) is False
    assert is_stale(stale, TS, cadence, staleness_cadence_mult=2.0) is True


def test_clock_drift_thresholds():
    assert clock_drift_status(200, warn_ms=500, pause_ms=2000) is DriftStatus.OK
    assert clock_drift_status(800, warn_ms=500, pause_ms=2000) is DriftStatus.WARN
    assert clock_drift_status(2500, warn_ms=500, pause_ms=2000) is DriftStatus.PAUSE
    assert clock_drift_status(-2500, warn_ms=500, pause_ms=2000) is DriftStatus.PAUSE  # abs
