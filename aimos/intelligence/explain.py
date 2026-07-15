"""Explainability engine (§6.8, card P3-T4).

Deterministic template renderer — collects ``reasons`` from every engine, orders
evidence by contribution magnitude, and emits the top-N as
``MarketUnderstanding.reasons`` plus a one-paragraph summary. Pure functions so
backtests stay reproducible (no LLM in the decision path, §15.3).
"""

from __future__ import annotations

from typing import Iterable

from aimos.core.schemas import Direction, EvidenceBundle
from aimos.intelligence.base import effective_reliability


def _contribution(ev, tf_weights) -> float:
    return ev.strength * effective_reliability(ev, tf_weights)


def top_evidence_reasons(
    bundle: EvidenceBundle, tf_weights, top_n: int
) -> list[str]:
    """Human sentences for the strongest evidence, ordered by |contribution|."""
    ranked = sorted(
        (e for e in bundle.evidences if e.direction is not Direction.NEUTRAL),
        key=lambda e: _contribution(e, tf_weights),
        reverse=True,
    )
    out: list[str] = []
    for e in ranked[:top_n]:
        out.append(
            f"{e.name} ({e.direction.value}, {e.timeframe.value}): "
            f"strength {e.strength:.2f} × reliability {e.reliability:.2f}"
        )
    return out


def build_reasons(
    engine_reasons: Iterable[str],
    bundle: EvidenceBundle,
    tf_weights,
    top_n: int,
) -> list[str]:
    """Merge engine reasons with the top-evidence sentences (§6.8)."""
    reasons: list[str] = list(engine_reasons)
    reasons.extend(top_evidence_reasons(bundle, tf_weights, top_n))
    return reasons[:top_n]


def summary_paragraph(
    symbol: str, regime: str, behavior: str, p_up: float, confidence: float
) -> str:
    return (
        f"{symbol}: regime {regime}, behavior {behavior}. "
        f"Fused P(up)={p_up:.2f} at confidence {confidence:.2f}."
    )


__all__ = ["build_reasons", "summary_paragraph", "top_evidence_reasons"]
