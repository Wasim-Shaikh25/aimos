"""Stablecoin depeg guard (§16.1 B-3, card P15-T1).

Polls each allowed stable's price vs USD (proxied by its /USDT rate, USDT≈USD).
If any stable deviates more than ``depeg_guard_bps`` from 1.0:
  (a) that quote's markets are suspended,
  (b) a ``headline_shock``-class risk evidence is emitted, and
  (c) a 🚨 risk alert is published to the event bus.

Cross-exchange arbitrage must convert both legs to USD using live stable rates
before computing dislocation (§5.11 update) — this guard is the source of those
rates. Pure decision function + an optional bus publish helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from aimos.core.bus import EventBus, Topic
from aimos.core.schemas import Direction, Evidence, Timeframe


@dataclass(frozen=True)
class DepegCheck:
    quote: str
    rate: float  # observed stable/USD rate
    deviation_bps: float
    depegged: bool


def check_depeg(quote: str, rate_vs_usd: float, depeg_guard_bps: float) -> DepegCheck:
    """Evaluate one stable's peg. ``rate_vs_usd`` ≈ 1.0 when healthy."""
    deviation_bps = abs(rate_vs_usd - 1.0) * 10_000.0
    return DepegCheck(
        quote=quote,
        rate=rate_vs_usd,
        deviation_bps=deviation_bps,
        depegged=deviation_bps > depeg_guard_bps,
    )


def depeg_evidence(check: DepegCheck, timestamp: datetime) -> Evidence:
    """A headline_shock-class risk evidence for a depegged stable (§16.1 B-3).

    ``symbol`` is the depegged quote; ``meta.risk_gate`` hard-raises risk in the
    Layer-2 risk engine (§5.10.3 / §6.6), and ``depeg`` flags the cause.
    """
    return Evidence(
        source="universe.depeg_guard",
        symbol=check.quote,
        timeframe=Timeframe.M5,
        timestamp=timestamp,
        name="headline_shock",
        value=check.deviation_bps,
        direction=Direction.BEARISH,
        strength=1.0,
        reliability=1.0,
        meta={"risk_gate": True, "depeg": True, "rate": check.rate},
    )


def publish_depeg_alert(bus: EventBus, check: DepegCheck) -> None:
    """Emit the 🚨 risk alert for a depeg (§16.1 B-3 c)."""
    bus.publish(
        Topic.RISK_ALERT,
        {
            "kind": "depeg",
            "quote": check.quote,
            "rate": check.rate,
            "deviation_bps": check.deviation_bps,
            "message": f"🚨 RISK: {check.quote} depeg — rate {check.rate:.4f} "
            f"({check.deviation_bps:.0f}bps off peg); quote suspended",
        },
    )


__all__ = ["DepegCheck", "check_depeg", "depeg_evidence", "publish_depeg_alert"]
