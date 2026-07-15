"""Depeg guard tests (§16.1 B-3 — card P15-T1 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.bus import EventBus, Topic
from aimos.universe.depeg import check_depeg, depeg_evidence, publish_depeg_alert
from aimos.universe.registry import Registry
from aimos.universe.discovery import MarketInfo

TS = datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_healthy_stable_not_depegged():
    c = check_depeg("USDC", 1.0005, depeg_guard_bps=80)
    assert not c.depegged
    assert c.deviation_bps == pytest.approx(5.0)


def test_usdc_depeg_sim_suspends_and_alerts():
    # USDC at 0.985 → 150bps off peg > 80bps guard
    c = check_depeg("USDC", 0.985, depeg_guard_bps=80)
    assert c.depegged
    assert c.deviation_bps == pytest.approx(150.0)

    # emits a headline_shock-class risk evidence with risk_gate
    ev = depeg_evidence(c, TS)
    assert ev.name == "headline_shock"
    assert ev.meta["risk_gate"] is True
    assert ev.meta["depeg"] is True
    assert ev.strength == 1.0

    # publishes a risk alert on the bus
    bus = EventBus()
    got: list = []
    bus.subscribe(Topic.RISK_ALERT, lambda t, p: got.append(p))
    publish_depeg_alert(bus, c)
    assert len(got) == 1
    assert got[0]["kind"] == "depeg"
    assert got[0]["quote"] == "USDC"


def test_depeg_suspends_quote_in_registry():
    reg = Registry(primary_exchange="binance")
    reg.add_market(MarketInfo(
        exchange="kraken", symbol="SOL/USDC", base="SOL", quote="USDC", type="spot",
        active=True, min_notional=5.0, lot_step=0.001, taker_bps=7.5, maker_bps=2.0,
    ))
    c = check_depeg("USDC", 0.985, depeg_guard_bps=80)
    if c.depegged:
        reg.suspend_quote(c.quote)
    assert reg.venues("SOL") == []  # SOL/USDC suspended, no other venue
