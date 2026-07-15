"""Tier engine — T1/T2/T3 with hysteresis (§16.1 D, card P15-T3).

Tiering keeps "all crypto" computable: the full 13-engine pipeline runs only on
T1 (max 12), a lighter set on T2 (max 60), and an hourly screener on T3 (all
filtered). Trading is allowed ONLY for T1 assets — a risk gate (§7.4 rule 6).

T1 membership uses hysteresis to avoid churn: an asset enters T1 when its
opportunity_score ≥ ``promote`` (65) and there is a free slot; it exits only
after its score stays < ``demote`` (50) for ``demote_scans`` (3) consecutive
scans. ``t1_provisional`` slots are reserved separately for ignition fast-track
(§23.11) and are not consumed by normal promotion.

Every tier change is journaled via the change callback (T1 changes are also
Telegram-notified upstream). Caps are enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class Tier(str, Enum):
    T1 = "t1"
    T2 = "t2"
    T3 = "t3"
    T1_PROVISIONAL = "t1_provisional"


@dataclass(frozen=True)
class TierChange:
    base: str
    old: Optional[Tier]
    new: Tier
    reason: str


TierChangeSink = Callable[[TierChange], None]


@dataclass
class TierEngine:
    t1_max: int = 12
    t2_max: int = 60
    t1_provisional_max: int = 3
    promote: float = 65.0
    demote: float = 50.0
    demote_scans: int = 3
    on_change: Optional[TierChangeSink] = None

    _tier: dict[str, Tier] = field(default_factory=dict)
    _below_streak: dict[str, int] = field(default_factory=dict)
    _provisional: set[str] = field(default_factory=set)

    # -- queries -------------------------------------------------------------

    def tier_of(self, base: str) -> Tier:
        return self._tier.get(base.upper(), Tier.T3)

    def t1_members(self) -> set[str]:
        return {b for b, t in self._tier.items() if t == Tier.T1}

    def t2_members(self) -> set[str]:
        return {b for b, t in self._tier.items() if t == Tier.T2}

    def is_tradable(self, base: str) -> bool:
        """§7.4 rule 6: only T1 (incl. provisional) may trade."""
        return self.tier_of(base) in (Tier.T1, Tier.T1_PROVISIONAL)

    # -- provisional (ignition fast-track, §23.11) --------------------------

    def add_provisional(self, base: str) -> bool:
        """Fast-track an igniting asset into a reserved provisional slot."""
        base = base.upper()
        if base in self._provisional:
            return True
        if len(self._provisional) >= self.t1_provisional_max:
            return False
        old = self._tier.get(base)
        self._provisional.add(base)
        self._tier[base] = Tier.T1_PROVISIONAL
        self._emit(TierChange(base, old, Tier.T1_PROVISIONAL, "ignition fast-track"))
        return True

    def clear_provisional(self, base: str) -> None:
        base = base.upper()
        if base in self._provisional:
            self._provisional.discard(base)
            old = self._tier.pop(base, None)
            self._tier[base] = Tier.T3
            self._emit(TierChange(base, old, Tier.T3, "ignition window closed"))

    # -- main update ---------------------------------------------------------

    def update(
        self,
        opportunity_scores: dict[str, float],
        watch_ranking: Optional[list[str]] = None,
    ) -> list[TierChange]:
        """Apply one scan's hysteresis + tier assignment. Returns changes.

        ``opportunity_scores``: base → score (0-100) for candidates. ``watch_ranking``:
        bases ordered best-first for T2 membership (liquidity+volume+coin_health,
        §16.1 D); defaults to score order.
        """
        changes: list[TierChange] = []

        # 1. Demotion of current T1 members via the below-threshold streak.
        for base in list(self.t1_members()):
            score = opportunity_scores.get(base, 0.0)
            if score < self.demote:
                self._below_streak[base] = self._below_streak.get(base, 0) + 1
                if self._below_streak[base] >= self.demote_scans:
                    self._set_tier(base, Tier.T2, "hysteresis demote (score<demote×N)", changes)
                    self._below_streak.pop(base, None)
            else:
                self._below_streak[base] = 0

        # 2. Promotion into free T1 slots, best score first.
        promotable = sorted(
            (b for b, s in opportunity_scores.items() if s >= self.promote and self.tier_of(b) != Tier.T1),
            key=lambda b: opportunity_scores[b],
            reverse=True,
        )
        for base in promotable:
            if len(self.t1_members()) >= self.t1_max:
                break
            self._set_tier(base, Tier.T1, "promote (score≥promote)", changes)
            self._below_streak[base] = 0

        # 3. T2 assignment (capped) from the watch ranking, excluding T1.
        ranking = watch_ranking or sorted(
            opportunity_scores, key=lambda b: opportunity_scores[b], reverse=True
        )
        t1 = self.t1_members() | self._provisional
        placed = 0
        for base in ranking:
            base = base.upper()
            if base in t1:
                continue
            if placed >= self.t2_max:
                break
            if self.tier_of(base) != Tier.T2:
                self._set_tier(base, Tier.T2, "watch rank", changes)
            placed += 1

        return changes

    # -- internals -----------------------------------------------------------

    def _set_tier(self, base: str, new: Tier, reason: str, sink: list[TierChange]) -> None:
        base = base.upper()
        old = self._tier.get(base)
        if old == new:
            return
        self._tier[base] = new
        change = TierChange(base, old, new, reason)
        sink.append(change)
        self._emit(change)

    def _emit(self, change: TierChange) -> None:
        if self.on_change is not None:
            self.on_change(change)


__all__ = ["Tier", "TierChange", "TierEngine"]
