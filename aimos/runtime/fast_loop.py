"""Scalp fast-loop context gating (§17.2, card P6-T6).

Two-loop design: the slow loop (5m) produces the MarketUnderstanding "context";
the fast loop (1m + streams) runs scalp plugins ONLY inside that context. This
module is the context gate + the LOW_FIDELITY stamp rule (§17.5). Not in the
linted layers.
"""

from __future__ import annotations

from typing import Any, Mapping

from aimos.core.schemas import MarketUnderstanding


def scalp_context_ok(
    mu: MarketUnderstanding,
    gate_cfg: Mapping[str, Any],
    is_tier1: bool,
    in_funding_window: bool,
    stream_healthy: bool = True,
) -> bool:
    """Scalping allowed only inside the slow-loop context (§17.2 rule 1)."""
    return (
        mu.regime.value in gate_cfg["allowed_regimes"]
        and mu.confidence >= float(gate_cfg["min_confidence"])
        and mu.risk_score <= float(gate_cfg["max_risk_score"])
        and is_tier1
        and not in_funding_window
        and stream_healthy
    )


def fidelity_stamp(used_recorded_book: bool) -> str:
    """§17.5: candle-only 1m backtests are stamped LOW_FIDELITY and cannot pass
    the promotion gate; recorded-order-book backtests are full-fidelity."""
    return "FULL" if used_recorded_book else "LOW_FIDELITY"


__all__ = ["fidelity_stamp", "scalp_context_ok"]
