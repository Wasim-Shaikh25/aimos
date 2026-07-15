"""Decision Fusion engine (§6.4, §25.2, card P3-T3).

Combines the rule/bayes/ml opinions with confidence-weighted fusion, then applies
the conflict penalties (disagreement, poor liquidity, sentiment-vs-book,
headline_shock). Produces the fused p_up/regime/behavior distributions, the
direction bias, and the ingredients the confidence engine (§6.7) needs
(disagreement + penalty multiplier). No averaging shortcuts (§6.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Mapping

from aimos.core.normalize import HALF
from aimos.core.schemas import Behavior, Direction, EngineOpinion, EvidenceBundle
from aimos.intelligence.base import first_named, has_name


@dataclass
class FusionResult:
    p_up: float
    regime_probs: dict[str, float]
    behavior_probs: dict[str, float]
    direction_bias: Direction
    disagreement: float
    penalty_mult: float  # extra confidence penalty from conflicts (§6.4)
    reasons: list[str] = field(default_factory=list)


class FusionEngine:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg  # params.intelligence subtree
        self.base_weights = cfg["fusion_weights"]
        self.conflict = cfg["conflict"]
        self.bias = cfg["direction_bias"]

    def fuse(self, opinions: list[EngineOpinion], bundle: EvidenceBundle) -> FusionResult:
        reasons: list[str] = []
        weights = {o.engine: float(self.base_weights.get(o.engine, 0.0)) * o.confidence for o in opinions}
        total_w = sum(weights.values())

        p_up = self._weighted_p_up(opinions, weights, total_w)
        regime_probs = self._weighted_dist(opinions, weights, total_w, "regime_probs")
        behavior_probs = self._weighted_dist(opinions, weights, total_w, "behavior_probs")

        disagreement = self._disagreement(opinions)
        penalty_mult = 1.0

        # penalty 1: engines disagree
        if disagreement > float(self.conflict["disagreement_threshold"]):
            penalty_mult *= float(self.conflict["disagreement_conf_mult"])
            reasons.append("engines disagree")

        # penalty 2: poor liquidity (thin_book or wide spread z)
        if self._poor_liquidity(bundle):
            penalty_mult *= float(self.conflict["liquidity_conf_mult"])
            reasons.append("poor liquidity")

        # penalty 3: sentiment vs order book → shift mass to UNCLEAR
        if self._sentiment_book_conflict(bundle):
            behavior_probs = self._shift_to_unclear(behavior_probs)
            reasons.append("mixed evidence: sentiment vs order book")

        # penalty 4: headline shock → pull p_up toward 0.5, cut confidence
        if has_name(bundle.evidences, "headline_shock"):
            pull = float(self.conflict["headline_shock_pull"])
            p_up = p_up + (HALF - p_up) * pull
            penalty_mult *= float(self.conflict["headline_shock_conf_mult"])
            reasons.append("headline shock")

        direction_bias = self._bias(p_up)
        return FusionResult(
            p_up=p_up, regime_probs=regime_probs, behavior_probs=behavior_probs,
            direction_bias=direction_bias, disagreement=disagreement,
            penalty_mult=penalty_mult, reasons=reasons,
        )

    # -- weighting -----------------------------------------------------------

    def _weighted_p_up(self, opinions, weights, total_w) -> float:
        if total_w <= 0:
            return HALF
        return sum(weights[o.engine] * o.p_up for o in opinions) / total_w

    def _weighted_dist(self, opinions, weights, total_w, field_name) -> dict[str, float]:
        acc: dict[str, float] = {}
        if total_w <= 0:
            # fall back to a simple average of provided distributions
            dists = [getattr(o, field_name) for o in opinions if getattr(o, field_name)]
            if not dists:
                return {}
            for dist in dists:
                for k, v in dist.items():
                    acc[k] = acc.get(k, 0.0) + v / len(dists)
            return acc
        for o in opinions:
            dist = getattr(o, field_name)
            for k, v in dist.items():
                acc[k] = acc.get(k, 0.0) + weights[o.engine] * v
        norm = sum(acc.values())
        if norm > 0:
            acc = {k: v / norm for k, v in acc.items()}
        return acc

    # -- conflicts -----------------------------------------------------------

    def _disagreement(self, opinions) -> float:
        active = [o for o in opinions if float(self.base_weights.get(o.engine, 0.0)) > 0]
        if len(active) < 2:
            return 0.0
        return max(abs(a.p_up - b.p_up) for a, b in combinations(active, 2))

    def _poor_liquidity(self, bundle: EvidenceBundle) -> bool:
        if has_name(bundle.evidences, "thin_book"):
            return True
        spread = first_named(bundle.evidences, "spread")
        if spread is not None and abs(spread.value) > float(self.conflict["liquidity_spread_z"]):
            return True
        return False

    def _sentiment_book_conflict(self, bundle: EvidenceBundle) -> bool:
        tone = first_named(bundle.evidences, "news_tone")
        book = first_named(bundle.evidences, "book_imbalance")
        if tone is None or book is None:
            return False
        return tone.direction is not book.direction and Direction.NEUTRAL not in (tone.direction, book.direction)

    def _shift_to_unclear(self, behavior_probs: dict[str, float]) -> dict[str, float]:
        shift = float(self.conflict["sentiment_book_shift"])
        out = {k: v * (1.0 - shift) for k, v in behavior_probs.items()}
        out[Behavior.UNCLEAR.value] = out.get(Behavior.UNCLEAR.value, 0.0) + shift
        norm = sum(out.values())
        return {k: v / norm for k, v in out.items()} if norm > 0 else out

    def _bias(self, p_up: float) -> Direction:
        if p_up >= float(self.bias["bull"]):
            return Direction.BULLISH
        if p_up <= float(self.bias["bear"]):
            return Direction.BEARISH
        return Direction.NEUTRAL


__all__ = ["FusionEngine", "FusionResult"]
