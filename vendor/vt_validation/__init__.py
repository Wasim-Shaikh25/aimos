# Adapted from HKUDS/Vibe-Trading (MIT) — statistical validation suite.
# Reference implementation (clean-room); the real Monte-Carlo permutation /
# bootstrap CI / walk-forward + run-card modules are copied at vendoring time
# (§20.2, §22.2A). Record the pinned SHA in vendor/VENDOR.md.
"""Backtest validation statistics (§20.2).

Deterministic given a seed so run cards with identical hashes reproduce identical
metrics (§13 test 7 extended to backtests). Promotion gates require permutation
p < 0.05 and a bootstrap Sharpe CI lower bound > 0 (§8.3, §17.5).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def _sharpe(returns: np.ndarray) -> float:
    std = returns.std(ddof=1) if len(returns) > 1 else 0.0
    return float(returns.mean() / std) if std > 0 else 0.0


def permutation_pvalue(
    returns: Sequence[float], n: int = 1000, seed: int = 0
) -> float:
    """Monte-Carlo permutation p-value that mean PnL beats sign-shuffled chance.

    Flips the sign of each return at random ``n`` times; p = fraction of shuffles
    whose mean ≥ the observed mean. Deterministic for a given seed.
    """
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 1.0
    observed = r.mean()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n, r.size))
    shuffled_means = (signs * r).mean(axis=1)
    return float((shuffled_means >= observed).mean())


def bootstrap_sharpe_ci(
    returns: Sequence[float], n: int = 1000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    """Bootstrap (1−alpha) CI for the Sharpe ratio. Gate requires lower > 0."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, r.size, size=(n, r.size))
    sharpes = np.array([_sharpe(r[i]) for i in idx])
    lo = float(np.quantile(sharpes, alpha / 2))
    hi = float(np.quantile(sharpes, 1 - alpha / 2))
    return (lo, hi)


__all__ = ["bootstrap_sharpe_ci", "permutation_pvalue"]
