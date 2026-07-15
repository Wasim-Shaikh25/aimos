"""Normalization helpers (§5.0).

The two standard transforms every observation engine uses to map a raw metric to
``strength ∈ [0, 1]``. Kept in ``core`` (not ``observation``) so the magic-number
lint (§23.12) governs decision-path *tunables* — the caps here are passed in from
config by callers, never hardcoded in the engines.

Also holds small scaling constants (percent, basis points) used when composing
evidence, so those math constants live in one audited place.
"""

from __future__ import annotations

PCT = 100.0
BPS = 10_000.0
HALF = 0.5


def z_to_strength(z: float, z_cap: float) -> float:
    """Map a z-score to 0..1; ``|z| >= z_cap`` saturates at 1 (§5.0)."""
    if z_cap <= 0:
        raise ValueError("z_cap must be positive")
    return min(abs(z) / z_cap, 1.0)


def ratio_to_strength(ratio: float, neutral: float, cap: float) -> float:
    """Map a ratio to 0..1; ``ratio == neutral`` → 0, saturates at ``cap`` (§5.0)."""
    span = cap - neutral
    if span <= 0:
        raise ValueError("cap must exceed neutral")
    return min(abs(ratio - neutral) / span, 1.0)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


__all__ = ["BPS", "HALF", "PCT", "clamp01", "ratio_to_strength", "z_to_strength"]
