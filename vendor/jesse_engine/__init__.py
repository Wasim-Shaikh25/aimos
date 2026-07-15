# Adapted from jesse-ai/jesse (MIT) — backtest metrics / correctness patterns.
# Reference implementation (clean-room); the real core engine + metrics + needed
# indicator math are copied at vendoring time and wrapped behind
# aimos/backtest/second_opinion.py for the §21.5 divergence check. Record the
# pinned SHA in vendor/VENDOR.md.
"""Second-opinion backtest metrics (§21.5).

Crypto-native, strict anti-lookahead culture. This reference provides the couple
of metrics the divergence check compares (total return, max drawdown) so three
independent engines (ours, VT, Jesse) can be diffed within tolerance.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def total_return(equity_curve: Sequence[float]) -> float:
    """Fractional total return from first to last equity point."""
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size < 2 or eq[0] == 0:
        return 0.0
    return float(eq[-1] / eq[0] - 1.0)


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction."""
    eq = np.asarray(equity_curve, dtype=float)
    if eq.size == 0:
        return 0.0
    running_max = np.maximum.accumulate(eq)
    drawdowns = (eq - running_max) / running_max
    return float(drawdowns.min())


__all__ = ["max_drawdown", "total_return"]
