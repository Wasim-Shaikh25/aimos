"""ML engine (§6.3, card P3-T1/P6-T1).

When a trained model artifact exists the engine builds the registry-ordered
feature vector and produces a REAL learned p_up + confidence (from validation
AUC). Without a model it is inert (0.5, confidence 0). Either way its FUSION
weight stays 0 until a human promotes it in config after the shadow window
(§8.3) — the engine works; it is simply not trusted yet, which is the correct
safety behavior, not a stub. Magic-number lint governs this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from aimos.core.normalize import HALF, clamp01
from aimos.core.schemas import Behavior, EngineOpinion, EvidenceBundle, Regime
from aimos.learning.features import feature_vector
from aimos.learning.model import LogisticModel


class MLEngine:
    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model: Optional[LogisticModel] = None
        if model_path and Path(model_path).exists():
            self.model = LogisticModel.load(model_path)

    def opine(
        self,
        bundle: EvidenceBundle,
        regime: Optional[Regime] = None,
        atr_pct: float = 0.0,
        rel_vol: float = 0.0,
    ) -> EngineOpinion:
        if self.model is None:
            return EngineOpinion(
                engine="ml", p_up=HALF,
                regime_probs={r.value: 1.0 / len(Regime) for r in Regime},
                behavior_probs={b.value: 1.0 / len(Behavior) for b in Behavior},
                confidence=0.0,
                reasons=["ml engine inert (no trained model; fusion weight 0)"],
            )
        vec = feature_vector(bundle, regime=regime, atr_pct=atr_pct, rel_vol=rel_vol)
        p_up = self.model.predict_one(vec)
        # confidence = |p_up−0.5|·2 × AUC-derived scalar (§6.3)
        auc_scalar = clamp01((self.model.val_auc - HALF) * 2.0)
        confidence = clamp01(abs(p_up - HALF) * 2.0 * auc_scalar)
        return EngineOpinion(
            engine="ml", p_up=float(p_up),
            regime_probs={},  # ML abstains from regime; fusion is rule-driven
            behavior_probs={},
            confidence=confidence,
            reasons=[f"ml model p_up={p_up:.3f} (val_auc {self.model.val_auc:.2f}, weight 0 until promoted)"],
        )


__all__ = ["MLEngine"]
