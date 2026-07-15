"""Intelligence-layer shared helpers (§6, §25.2).

Timeframe reliability multipliers (§25.2) and evidence-selection utilities used
by the rule and bayes engines. All tunables come from config (§23.12); the
magic-number lint governs this package.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from aimos.core.schemas import Direction, Evidence

IntelConfig = Mapping[str, Any]


def tf_multiplier(timeframe: str, tf_weights: Mapping[str, float]) -> float:
    """Timeframe reliability multiplier (§25.2). Unknown TF → 1.0."""
    return float(tf_weights.get(timeframe, 1.0))


def effective_reliability(ev: Evidence, tf_weights: Mapping[str, float]) -> float:
    """reliability × timeframe multiplier (§25.2 — applied before any math)."""
    return ev.reliability * tf_multiplier(ev.timeframe.value, tf_weights)


def directional(evidences: Iterable[Evidence]) -> list[Evidence]:
    return [e for e in evidences if e.direction is not Direction.NEUTRAL]


def has_name(evidences: Iterable[Evidence], name: str) -> bool:
    return any(e.name == name for e in evidences)


def first_named(evidences: Iterable[Evidence], name: str) -> Evidence | None:
    for e in evidences:
        if e.name == name:
            return e
    return None


def named(evidences: Iterable[Evidence], name: str) -> list[Evidence]:
    return [e for e in evidences if e.name == name]


def sign(direction: Direction) -> int:
    if direction is Direction.BULLISH:
        return 1
    if direction is Direction.BEARISH:
        return -1
    return 0


__all__ = [
    "IntelConfig",
    "directional",
    "effective_reliability",
    "first_named",
    "has_name",
    "named",
    "sign",
    "tf_multiplier",
]
