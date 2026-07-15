"""Jesse second-opinion cross-check (§21.5, card P5-T9).

Wraps the vendored Jesse metrics as an independent backtester. Two independent
engines agreeing within tolerance is strong correctness evidence; any pairwise
divergence > 15% on total return auto-files an "engine divergence" proposal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from vendor.jesse_engine import max_drawdown, total_return


@dataclass
class DivergenceReport:
    our_total_return: float
    jesse_total_return: float
    divergence_pct: float
    diverged: bool
    proposal: Optional[str] = None


def cross_check(
    our_equity: Sequence[float],
    jesse_equity: Sequence[float],
    tolerance_pct: float = 15.0,
) -> DivergenceReport:
    """Compare total return from both engines; flag divergence > tolerance (§21.5)."""
    ours = total_return(our_equity)
    jesse = total_return(jesse_equity)
    denom = abs(ours) if abs(ours) > 1e-9 else 1.0
    divergence = abs(ours - jesse) / denom * 100.0
    diverged = divergence > tolerance_pct
    proposal = None
    if diverged:
        proposal = (f"engine divergence: ours {ours:+.2%} vs Jesse {jesse:+.2%} "
                    f"({divergence:.1f}% > {tolerance_pct}%) — investigate")
    return DivergenceReport(ours, jesse, divergence, diverged, proposal)


__all__ = ["DivergenceReport", "cross_check"]
