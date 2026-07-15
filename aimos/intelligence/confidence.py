"""Confidence engine (§6.7, card P3-T4).

meta-confidence = agreement × evidence_coverage × regime_certainty × penalty_mult

* agreement = 1 − max pairwise engine disagreement (from fusion),
* evidence_coverage = fraction of profile-enabled engines that produced ≥1
  evidence this pass (§25.7 — denominator is engines ENABLED IN PROFILE),
* regime_certainty = max fused regime probability,
* penalty_mult = the extra conflict penalties fusion accumulated (§6.4).

Below ``min_confidence`` the Layer-3 evaluator forces NO_TRADE (§6.7).
"""

from __future__ import annotations

from typing import Mapping

from aimos.core.normalize import clamp01


def evidence_coverage(engines_reporting: int, coverage_engines: int) -> float:
    """Fraction of profile-enabled engines that produced evidence (§25.7)."""
    if coverage_engines <= 0:
        return 0.0
    return clamp01(engines_reporting / coverage_engines)


def compute_confidence(
    disagreement: float,
    coverage: float,
    regime_certainty: float,
    penalty_mult: float,
) -> float:
    """§6.7 product, with the §6.4 conflict penalty multiplier applied."""
    agreement = 1.0 - disagreement
    return clamp01(agreement * coverage * regime_certainty * penalty_mult)


__all__ = ["compute_confidence", "evidence_coverage"]
