"""Ignition detector (§23.11-A, card P5-T5).

Detects assets beginning violent repricings early enough to trade the middle of
the move. Two parts: a trigger (all conditions required) and an
organic-vs-manipulation classifier that BLOCKS the ignition evidence (forces
NEUTRAL + ``pnd_suspect``) whenever any pump-and-dump tell is present. Blocked
ignitions are still emitted/journaled so the ML engine learns the PnD pattern.

All thresholds from ``config/ignition.yaml``; the whole-market miniTicker stream
plumbing and the T1-provisional fast-track live in the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from aimos.core.schemas import Direction, Evidence, Timeframe


@dataclass
class IgnitionInput:
    ret_5m_z: float  # 5m return z-score vs the asset's own 30d distribution
    rel_vol_1m: float  # 1m volume / its 20-period average
    persistence_count: int  # consecutive minutes the conditions have held
    move_from_1h_pct: float  # % move from the 1h-ago price
    direction: Direction  # up/down direction of the move
    # classifier inputs (§23.11-A)
    cross_venue_frac: float = 1.0  # fraction of the move magnitude seen on peers
    book_depth_grew: bool = True  # did depth within 1% grow with price?
    spoof_or_divergence: bool = False  # spoof walls or venue_divergence_volume
    corroborated: bool = True  # news/funding/OI/whale/sector within 10 min
    listing_age_days: float = 365.0  # noqa: magic — safe default; runtime passes real age
    passes_filters: bool = True


@dataclass
class IgnitionResult:
    evidence: Evidence | None
    triggered: bool
    blocked: bool
    reasons: list[str] = field(default_factory=list)


class IgnitionDetector:
    def __init__(self, cfg: Mapping[str, Any], reliability: float) -> None:
        self.ig = cfg["ignition"]  # config/ignition.yaml `ignition:` block
        self.reliability = reliability  # weights.yaml reliability.ignition

    def detect(self, symbol: str, now: datetime, inp: IgnitionInput) -> IgnitionResult:
        ig = self.ig
        # -- trigger (all required) --
        triggered = (
            inp.ret_5m_z >= float(ig["ret_5m_z_min"])
            and inp.rel_vol_1m >= float(ig["rel_vol_1m_min"])
            and inp.persistence_count >= int(ig["persistence_bars"])
            and inp.move_from_1h_pct <= float(ig["max_move_already_pct"])
        )
        if not triggered:
            return IgnitionResult(None, triggered=False, blocked=False,
                                  reasons=["no ignition trigger" if inp.move_from_1h_pct <= float(ig["max_move_already_pct"])
                                           else "move already too large — observe only"])

        # -- organic-vs-PnD classifier --
        blocks: list[str] = []
        if inp.cross_venue_frac < float(ig["cross_venue_min_frac"]):
            blocks.append("single-venue move (absent on peers)")
        if not inp.book_depth_grew:
            blocks.append("book hollow (depth didn't grow with price)")
        if inp.spoof_or_divergence:
            blocks.append("spoof walls / venue divergence")
        if not inp.corroborated:
            blocks.append("no corroboration within 10 min")
        if inp.listing_age_days < float(ig["min_listing_age_days"]) or not inp.passes_filters:
            blocks.append("fails filters / too young")

        blocked = bool(blocks)
        direction = Direction.NEUTRAL if blocked else inp.direction
        evidence = Evidence(
            source="ignition.detector", symbol=symbol, timeframe=Timeframe.M5,
            timestamp=now, name="ignition", value=inp.move_from_1h_pct,
            direction=direction, strength=1.0 if not blocked else 0.0,
            reliability=self.reliability,
            meta={"pnd_suspect": blocked, "pct": inp.move_from_1h_pct,
                  "rel_vol_1m": inp.rel_vol_1m, "blocks": blocks},
        )
        return IgnitionResult(evidence, triggered=True, blocked=blocked, reasons=blocks)


__all__ = ["IgnitionDetector", "IgnitionInput", "IgnitionResult"]
