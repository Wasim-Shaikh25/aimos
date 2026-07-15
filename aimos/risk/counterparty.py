"""Counterparty (venue) risk framework (§24.2, card P5-T7).

Exchange balance is a credit exposure to the exchange and gets limits like any
counterparty (the FTX lesson). Hard cap per venue, a degrade ladder
(watch/alert/critical), and sizing headroom. Config-driven (config/counterparty.yaml).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class DegradeLevel(str, Enum):
    OK = "ok"
    WATCH = "watch"
    ALERT = "alert"
    CRITICAL = "critical"


@dataclass
class VenueCheck:
    venue: str
    exposure_pct: float
    over_cap: bool
    headroom_pct: float


class CounterpartyRisk:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg
        self.max_pct = float(cfg["max_equity_pct_per_exchange"])

    def check(self, venue: str, exposure_pct: float) -> VenueCheck:
        return VenueCheck(
            venue=venue, exposure_pct=exposure_pct,
            over_cap=exposure_pct > self.max_pct,
            headroom_pct=max(self.max_pct - exposure_pct, 0.0),
        )

    def vetoes_new_position(self, venue: str, exposure_pct: float, new_alloc_pct: float) -> bool:
        """Sizing also caps by remaining venue headroom (§24.2)."""
        return exposure_pct + new_alloc_pct > self.max_pct

    @staticmethod
    def degrade_level(
        signal_count: int, insolvency_flag: bool
    ) -> DegradeLevel:
        """Map venue-health signals to a ladder rung (§24.2)."""
        if insolvency_flag:
            return DegradeLevel.CRITICAL
        if signal_count >= 2:
            return DegradeLevel.ALERT
        if signal_count == 1:
            return DegradeLevel.WATCH
        return DegradeLevel.OK


__all__ = ["CounterpartyRisk", "DegradeLevel", "VenueCheck"]
