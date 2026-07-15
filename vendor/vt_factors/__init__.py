# Adapted from HKUDS/Vibe-Trading (MIT) — Alpha Zoo + operator layer.
# Reference implementation (clean-room); the real zoos (Qlib158/Alpha101/GTJA191/
# academic) + their lookahead-banned operator layer are copied at vendoring time,
# preserving Apache-2 Qlib headers and per-zoo LICENSE.md (§20.1, §22.2A). Record
# the pinned SHA in vendor/VENDOR.md.
"""Cross-sectional factor math (§20.1).

The operator layer bans lookahead at the operator boundary. This reference ships
one deterministic alpha (cross-sectional momentum z-score) plus the cross-section
utilities the factor engine (§20.1) fans out per asset.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def cross_sectional_zscore(values: Sequence[float]) -> np.ndarray:
    """Standardize a cross-section to mean 0, std 1 (ddof=0). Flat → zeros."""
    arr = np.asarray(values, dtype=float)
    std = arr.std()
    if std == 0:
        return np.zeros_like(arr)
    return (arr - arr.mean()) / std


def alpha_momentum(closes: Sequence[float], lookback: int) -> float:
    """Reference alpha: simple ``lookback``-bar return (no lookahead).

    ``(close[-1] / close[-1-lookback]) − 1``. Needs > ``lookback`` points.
    """
    arr = np.asarray(closes, dtype=float)
    if len(arr) <= lookback:
        raise ValueError("need more than `lookback` closes")
    return float(arr[-1] / arr[-1 - lookback] - 1.0)


__all__ = ["alpha_momentum", "cross_sectional_zscore"]
