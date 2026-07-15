"""ML engine — inert until trained (§6.3, card P3-T3).

Phase 1-3: returns a neutral opinion (p_up 0.5, confidence 0) with fusion weight
0. It stays inert until the journal has enough labeled samples and the shadow →
promotion ladder (§8.3) raises its fusion weight via config (a human step).
The feature vector width is fixed by the evidence registry (§25.6).
"""

from __future__ import annotations

from aimos.core.normalize import HALF
from aimos.core.schemas import Behavior, EngineOpinion, EvidenceBundle, Regime


class MLEngine:
    def opine(self, bundle: EvidenceBundle) -> EngineOpinion:
        return EngineOpinion(
            engine="ml",
            p_up=HALF,
            regime_probs={r.value: 1.0 / len(Regime) for r in Regime},
            behavior_probs={b.value: 1.0 / len(Behavior) for b in Behavior},
            confidence=0.0,
            reasons=["ml engine inert (weight 0 until trained, §6.3)"],
        )


__all__ = ["MLEngine"]
