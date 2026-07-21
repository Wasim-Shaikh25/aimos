"""Strategy evaluator (§7.3, §23.9C, §25.4-25.5, card P4-T1).

Scores candidate TradePlans, enforces the cost-fraction gate, and picks the
winner — with NO_TRADE (RiskOff baseline) as a first-class candidate everything
else must beat. Negative-EV candidates are never taken (§7.3).

Reproduces §25.9 step 7-8 exactly: a bullish setup whose post-cost EV is ≤ 0 is
dropped and NO_TRADE wins.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from aimos.core.normalize import BPS, PCT, clamp01
from aimos.core.schemas import Action, MarketUnderstanding, TradePlan


def risk_bps(plan: TradePlan) -> float:
    """|entry − stop| / entry × 10_000 (§25.5). 0 when geometry missing."""
    if not plan.entry or plan.stop_loss is None or plan.entry == 0:
        return 0.0
    return abs(plan.entry - plan.stop_loss) / plan.entry * BPS


def ev_normalized(ev: float, cap_r: float) -> float:
    """clamp(ev / cap, 0, 1) — cap_r R of EV saturates the score term (§25.5)."""
    if cap_r <= 0:
        return 0.0
    return clamp01(ev / cap_r)


def expected_value(plan: TradePlan, losing_r: float) -> float:
    """EV in R units, cost-adjusted (§7.3): p·rr − (1−p)·losing_r − cost_r."""
    p = plan.confidence  # calibrated win-prob proxy (recalibrated §8.4)
    rr = plan.expected_rr or 0.0
    rb = risk_bps(plan)
    cost_r = plan.expected_costs_bps / rb if rb > 0 else 0.0
    return p * rr - (1.0 - p) * losing_r - cost_r


class Evaluator:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg  # params.execution subtree
        self.weights = cfg["eval_weights"]
        self.no_trade_baseline = float(cfg["no_trade_baseline"])
        self.min_trade_score = float(cfg["min_trade_score"])
        self.cap_r = float(cfg["ev_norm_cap_r"])
        self.max_cost_fraction = float(cfg["max_cost_fraction"])
        self.losing_r = float(cfg["losing_trade_r"])

    def evaluate(self, candidates: list[TradePlan], mu: MarketUnderstanding) -> TradePlan:
        scored: list[TradePlan] = []
        no_trade: TradePlan | None = None
        for c in candidates:
            if c.action is Action.NO_TRADE:
                c.score = self.no_trade_baseline
                no_trade = c
                scored.append(c)
                continue
            # a directional candidate with no usable stop distance can't be
            # cost-adjusted or sized — its EV/cost math is meaningless, so it must
            # never win (and thereby suppress a valid candidate). Drop it up front.
            if risk_bps(c) <= 0:
                c.reasons.append("rejected: no usable stop geometry")
                continue
            if self._cost_fraction_exceeded(c):
                c.reasons.append("rejected: costs exceed max cost fraction")
                continue
            ev = expected_value(c, self.losing_r)
            if not math.isfinite(ev) or ev <= 0:
                c.reasons.append(f"dropped: EV {ev:+.3f} not positive-finite")
                continue
            c.score = self._score(c, mu, ev)
            scored.append(c)

        if not scored:
            return no_trade or self._synthetic_no_trade(mu)
        best = max(scored, key=lambda c: c.score)
        if best.action is not Action.NO_TRADE and best.score < self.min_trade_score:
            return no_trade or self._synthetic_no_trade(mu)
        return best

    # -- internals -----------------------------------------------------------

    def _cost_fraction_exceeded(self, plan: TradePlan) -> bool:
        rb = risk_bps(plan)
        gross_move_bps = (plan.expected_rr or 0.0) * rb
        if gross_move_bps <= 0:
            return False
        return plan.expected_costs_bps > self.max_cost_fraction * gross_move_bps

    def _score(self, c: TradePlan, mu: MarketUnderstanding, ev: float) -> float:
        w = self.weights
        return (
            float(w["ev"]) * ev_normalized(ev, self.cap_r)
            + float(w["confidence"]) * c.confidence
            + float(w["opportunity"]) * mu.opportunity_score / PCT
            + float(w["risk"]) * (1.0 - mu.risk_score / PCT)
        )

    def _synthetic_no_trade(self, mu: MarketUnderstanding) -> TradePlan:
        return TradePlan(
            plugin="RiskOff", symbol=mu.symbol, action=Action.NO_TRADE,
            score=self.no_trade_baseline, reasons=["no positive-EV candidate"],
        )


__all__ = ["Evaluator", "ev_normalized", "expected_value", "risk_bps"]
