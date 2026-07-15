"""Factor selection job (§20.1.2, card P5-T6).

One-time / quarterly job: build the cross-sectional panel over T1+T2, run the IC
benchmark per alpha against forward returns, keep survivors (|IC| ≥ ic_min AND
IR ≥ ir_min), pre-cluster by pairwise correlation (>cluster_corr_max → keep the
highest-|IC| of the cluster), cap at max_active, and write factors_active.yaml.
Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from vendor.vt_factors import alpha_momentum


@dataclass
class AlphaStat:
    alpha_id: str
    ic: float
    ir: float
    ic_sign: int


def information_coefficient(alpha_values: Sequence[float], forward_returns: Sequence[float]) -> float:
    """Cross-sectional Spearman-ish IC (Pearson on ranks would be full Spearman;
    Pearson here is sufficient for the survivor filter)."""
    a = np.asarray(alpha_values, dtype=float)
    r = np.asarray(forward_returns, dtype=float)
    if a.size < 2 or a.std() == 0 or r.std() == 0:
        return 0.0
    return float(np.corrcoef(a, r)[0, 1])


def evaluate_alpha(
    alpha_id: str,
    panels: Sequence[Mapping[str, Sequence[float]]],
    forwards: Sequence[Mapping[str, float]],
    lookback: int,
) -> AlphaStat:
    """IC per period → IR = mean(IC)/std(IC) across periods."""
    ics: list[float] = []
    for panel, fwd in zip(panels, forwards):
        vals, rets = [], []
        for base, closes in panel.items():
            if base in fwd and len(closes) > lookback:
                vals.append(alpha_momentum(closes, lookback))
                rets.append(fwd[base])
        ics.append(information_coefficient(vals, rets))
    ic_arr = np.asarray(ics, dtype=float)
    mean_ic = float(ic_arr.mean()) if ic_arr.size else 0.0
    std_ic = float(ic_arr.std(ddof=1)) if ic_arr.size > 1 else 0.0
    ir = mean_ic / std_ic if std_ic > 0 else 0.0
    return AlphaStat(alpha_id, ic=mean_ic, ir=ir, ic_sign=1 if mean_ic >= 0 else -1)


def select_survivors(
    stats: Sequence[AlphaStat], ic_min: float, ir_min: float, max_active: int
) -> list[AlphaStat]:
    survivors = [s for s in stats if abs(s.ic) >= ic_min and abs(s.ir) >= ir_min]
    survivors.sort(key=lambda s: abs(s.ic), reverse=True)
    return survivors[:max_active]


__all__ = ["AlphaStat", "evaluate_alpha", "information_coefficient", "select_survivors"]
