"""Regime & behavior finalization (§6.5, card P3-T4).

Label = argmax of the fused distribution. If the argmax probability is below the
uncertainty threshold the label still stands but ``regime_certainty`` (the max
prob) informs the confidence engine (§6.7) — an uncertain regime lowers
confidence rather than changing the label.
"""

from __future__ import annotations

from typing import Mapping

from aimos.core.schemas import Behavior, Regime


def finalize_regime(regime_probs: Mapping[str, float]) -> tuple[Regime, float]:
    label, prob = _argmax(regime_probs)
    return Regime(label), prob


def finalize_behavior(behavior_probs: Mapping[str, float]) -> tuple[Behavior, float]:
    label, prob = _argmax(behavior_probs)
    return Behavior(label), prob


def _argmax(dist: Mapping[str, float]) -> tuple[str, float]:
    if not dist:
        raise ValueError("empty distribution")
    label = max(dist, key=lambda k: dist[k])
    return label, float(dist[label])


__all__ = ["finalize_behavior", "finalize_regime"]
