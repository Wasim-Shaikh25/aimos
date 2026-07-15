"""Calibration + drift math (§8.4, §23.7, cards P6-T1, P6-T2).

Isotonic regression (pool-adjacent-violators) for ML p_up calibration (§6.3) and
plugin-confidence calibration (§8.4); sensor-reliability recalibration
(``rel_new = clamp(2·hitrate − 0.5, lo, hi)``); and PSI drift for the model-drift
monitor. Pure numpy — not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class IsotonicModel:
    x: np.ndarray  # sorted breakpoints
    y: np.ndarray  # monotonic fitted values

    def predict(self, q: float) -> float:
        if self.x.size == 0:
            return q
        return float(np.interp(q, self.x, self.y))


def isotonic_fit(x: Sequence[float], y: Sequence[float]) -> IsotonicModel:
    """Non-decreasing fit of y on x via pool-adjacent-violators (unit weights)."""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if xa.size == 0:
        return IsotonicModel(np.array([]), np.array([]))
    order = np.argsort(xa)
    xs = xa[order]
    ys = ya[order]
    values: list[float] = []
    weights: list[float] = []
    for yi in ys:
        values.append(float(yi))
        weights.append(1.0)
        while len(values) > 1 and values[-2] > values[-1]:
            v2, w2 = values.pop(), weights.pop()
            v1, w1 = values.pop(), weights.pop()
            values.append((v1 * w1 + v2 * w2) / (w1 + w2))
            weights.append(w1 + w2)
    # expand pooled blocks back to per-sample fitted values
    fitted: list[float] = []
    for v, w in zip(values, weights):
        fitted.extend([v] * int(round(w)))
    return IsotonicModel(xs, np.asarray(fitted[: xs.size], dtype=float))


def recalibrate_reliability(hitrate: float, clamp_lo: float, clamp_hi: float) -> float:
    """§8.4: rel_new = clamp(2·hitrate − 0.5, lo, hi)."""
    return float(np.clip(2.0 * hitrate - 0.5, clamp_lo, clamp_hi))


def population_stability_index(
    expected: Sequence[float], actual: Sequence[float], bins: int = 10
) -> float:
    """PSI between a training (expected) and live (actual) distribution (§23.7)."""
    exp = np.asarray(expected, dtype=float)
    act = np.asarray(actual, dtype=float)
    if exp.size == 0 or act.size == 0:
        return 0.0
    edges = np.quantile(exp, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    e_hist, _ = np.histogram(exp, bins=edges)
    a_hist, _ = np.histogram(act, bins=edges)
    e_frac = np.clip(e_hist / max(exp.size, 1), 1e-6, None)
    a_frac = np.clip(a_hist / max(act.size, 1), 1e-6, None)
    return float(((a_frac - e_frac) * np.log(a_frac / e_frac)).sum())


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    if p.size == 0:
        return 0.0
    return float(((p - y) ** 2).mean())


__all__ = [
    "IsotonicModel",
    "brier_score",
    "isotonic_fit",
    "population_stability_index",
    "recalibrate_reliability",
]
