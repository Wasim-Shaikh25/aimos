"""ML feature builder (§6.3, §25.6, card P6-T1).

Flattens an EvidenceBundle into a fixed-width vector in evidence-registry order:
each registered name → strength × direction_sign (missing = 0), plus ATR%,
rel_vol, and a regime one-hot. The registry fixes the width forever (§25.6), so
adding an evidence name is a registry PR + a retrain note in MODELS.md. Not in
the linted layers.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from aimos.core.evidence_registry import EVIDENCE_NAMES, feature_index
from aimos.core.schemas import Direction, EvidenceBundle, Regime

_REGIMES = [r.value for r in Regime]


def _sign(direction: Direction) -> int:
    return {Direction.BULLISH: 1, Direction.BEARISH: -1}.get(direction, 0)


def feature_names() -> list[str]:
    """Stable column order: evidence names + context + regime one-hot."""
    return list(EVIDENCE_NAMES) + ["atr_pct", "rel_vol"] + [f"regime_{r}" for r in _REGIMES]


def feature_vector(
    bundle: EvidenceBundle,
    regime: Optional[Regime] = None,
    atr_pct: float = 0.0,
    rel_vol: float = 0.0,
) -> np.ndarray:
    """Fixed-width feature vector (§6.3). Missing evidence → 0."""
    idx = feature_index()
    width = len(EVIDENCE_NAMES)
    vec = np.zeros(width + 2 + len(_REGIMES), dtype=float)
    # evidence block: strongest per name wins (correlation handled in bayes)
    for e in bundle.evidences:
        base = e.name.split("_")[0] if e.name.startswith("factor_") else e.name
        key = "factor" if e.name.startswith("factor_") else e.name
        if key in idx:
            i = idx[key]
            val = e.strength * _sign(e.direction)
            if abs(val) > abs(vec[i]):
                vec[i] = val
    vec[width] = atr_pct
    vec[width + 1] = rel_vol
    if regime is not None:
        vec[width + 2 + _REGIMES.index(regime.value)] = 1.0
    return vec


__all__ = ["feature_names", "feature_vector"]
