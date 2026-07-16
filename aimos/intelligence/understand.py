"""Layer-2 orchestrator: EvidenceBundle → MarketUnderstanding (§6.0, card P3-T4).

Wires the three reasoning engines → fusion → regime/behavior finalize → scores →
confidence → explainability into the single ``MarketUnderstanding`` contract that
Layer 3 consumes. Deterministic and LLM-free (§15.3).
"""

from __future__ import annotations

from typing import Any, Optional

from aimos.core.normalize import PCT
from aimos.core.schemas import EvidenceBundle, MarketUnderstanding
from aimos.intelligence.bayes_engine import BayesEngine
from aimos.intelligence.base import first_named
from aimos.intelligence.confidence import compute_confidence, evidence_coverage
from aimos.intelligence.explain import build_reasons, summary_paragraph
from aimos.intelligence.finalize import finalize_behavior, finalize_regime
from aimos.intelligence.fusion import FusionEngine
from aimos.intelligence.ml_engine import MLEngine
from aimos.intelligence.rule_engine import RuleEngine
from aimos.intelligence import scores as sc


class IntelligenceLayer:
    """Constructs the engines once from Params and understands bundles."""

    def __init__(self, params: Any) -> None:
        self.params = params
        self.intel = params.intelligence.model_dump()
        self.weights = params.weights.model_dump()
        self.behavior_likelihoods = params.behavior_likelihoods.model_dump()
        self.rule = RuleEngine(self.intel)
        self.bayes = BayesEngine(self.intel, self.behavior_likelihoods)
        ml_model_path = self.intel.get("ml_model_path") or params.model_dump().get(
            "learning", {}
        ).get("ml", {}).get("model_path")
        self.ml = MLEngine(model_path=ml_model_path)
        self.fusion = FusionEngine(self.intel)

    def understand(
        self,
        bundle: EvidenceBundle,
        engines_reporting: int,
        score_ctx: Optional[sc.ScoreContext] = None,
        coverage_engines: Optional[int] = None,
    ) -> MarketUnderstanding:
        ctx = score_ctx or sc.ScoreContext()
        rule_op = self.rule.opine(bundle)
        bayes_op = self.bayes.opine(bundle)
        # ML features include the rule engine's regime one-hot (§6.3)
        rule_regime = self._argmax_regime(rule_op.regime_probs)
        kl = self._key_levels(bundle)
        atr = float(kl.get("atr", 0.0))
        price = float(kl.get("price", 0.0))
        atr_pct = (atr / price * PCT) if price > 0 else 0.0
        ml_op = self.ml.opine(bundle, regime=rule_regime, atr_pct=atr_pct)
        fused = self.fusion.fuse([rule_op, bayes_op, ml_op], bundle)

        regime, regime_certainty = finalize_regime(fused.regime_probs)
        behavior, _ = finalize_behavior(fused.behavior_probs)

        denom = coverage_engines if coverage_engines is not None else int(self.intel["coverage_engines"])
        coverage = evidence_coverage(engines_reporting, denom)
        confidence = compute_confidence(
            fused.disagreement, coverage, regime_certainty, fused.penalty_mult
        )

        trend_strength = self._trend_strength(bundle)
        scores_cfg = self.intel["scores"]
        health = sc.coin_health(
            bundle, fused.behavior_probs, trend_strength, self.weights, scores_cfg, ctx,
            self.weights["exchange_quality"],
        )
        risk = sc.risk_score(bundle, regime, self.weights, scores_cfg, ctx)
        opportunity = sc.opportunity(
            fused.p_up, confidence, fused.direction_bias, regime, health,
            self.weights, scores_cfg, ctx,
        )

        top_n = int(self.intel["explain_top_n"])
        reasons = build_reasons(fused.reasons, bundle, self.intel["tf_weights"], top_n)
        summary = summary_paragraph(
            bundle.symbol, regime.value, behavior.value, fused.p_up, confidence,
        )
        reasons = [summary, *reasons][:top_n]
        key_levels = self._key_levels(bundle)

        return MarketUnderstanding(
            symbol=bundle.symbol,
            timestamp=bundle.timestamp,
            regime=regime,
            regime_probs=fused.regime_probs,
            behavior=behavior,
            behavior_probs=fused.behavior_probs,
            direction_bias=fused.direction_bias,
            p_up=fused.p_up,
            horizon_minutes=int(self.params.horizon_minutes),
            confidence=confidence,
            coin_health=health,
            opportunity_score=opportunity,
            risk_score=risk,
            key_levels=key_levels,
            engine_votes={"rule": rule_op.p_up, "bayes": bayes_op.p_up, "ml": ml_op.p_up},
            reasons=reasons,
        )

    @staticmethod
    def _argmax_regime(regime_probs: dict) -> Optional[Any]:
        from aimos.core.schemas import Regime
        if not regime_probs:
            return None
        return Regime(max(regime_probs, key=lambda k: regime_probs[k]))

    @staticmethod
    def _trend_strength(bundle: EvidenceBundle) -> float:
        st = first_named(bundle.evidences, "structure_trend")
        return st.strength if st is not None else 0.0

    @staticmethod
    def _key_levels(bundle: EvidenceBundle) -> dict:
        # merge every engine's key_levels contributions (§5.1) — price_action
        # provides swings/price/atr, momentum provides ema50, etc.
        merged: dict = {}
        for e in bundle.evidences:
            kl = e.meta.get("key_levels")
            if isinstance(kl, dict):
                merged.update(kl)
        # surface cross-exchange dislocation so the arb plugin (P8) can consume it
        for e in bundle.evidences:
            if e.name == "price_dislocation":
                merged["dislocation"] = {"bps": e.meta.get("bps", e.value),
                                         "buy_venue": e.meta.get("buy_venue"),
                                         "sell_venue": e.meta.get("sell_venue")}
                break
        return merged


__all__ = ["IntelligenceLayer"]
