"""Rule engine (§6.1, §25.2-25.3, card P3-T1).

Deterministic, explainable scoring:
1. directional score → p_up (with timeframe multipliers, §25.2),
2. regime rules (first-match wins, evaluated on the configured regime TF),
3. behavior rules,
4. confidence (fraction of strong evidences, capped),
5. a human sentence appended to reasons for every rule that fires.

Regime rules that require raw price/ATR *history* (CRASH's 24h-drop magnitude,
RECOVERY's 30d-low) cannot be evaluated here — Layer 2 never inspects candles
(§25.3). SPEC-GAP: we key those regimes off the evidence observation already
emits (vol_shock bearish → CRASH candidate); RECOVERY is deferred until an
observation engine emits a recovery flag.
"""

from __future__ import annotations

from typing import Any, Mapping

from aimos.core.normalize import HALF
from aimos.core.schemas import (
    Behavior,
    Direction,
    EngineOpinion,
    EvidenceBundle,
    Regime,
)
from aimos.intelligence.base import (
    directional,
    effective_reliability,
    first_named,
    has_name,
    named,
    sign,
)

_REGIMES = [r.value for r in Regime]
_BEHAVIORS = [b.value for b in Behavior]


class RuleEngine:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        # cfg = params.intelligence subtree (dict)
        self.cfg = cfg
        self.tf_weights = cfg["tf_weights"]
        self.rule = cfg["rule"]

    def opine(self, bundle: EvidenceBundle) -> EngineOpinion:
        reasons: list[str] = []
        p_up = self._directional_score(bundle, reasons)
        regime_probs = self._regime(bundle, reasons)
        behavior_probs = self._behavior(bundle, reasons)
        confidence = self._confidence(bundle)
        return EngineOpinion(
            engine="rule",
            p_up=p_up,
            regime_probs=regime_probs,
            behavior_probs=behavior_probs,
            confidence=confidence,
            reasons=reasons,
        )

    # -- 1. directional score ------------------------------------------------

    def _directional_score(self, bundle: EvidenceBundle, reasons: list[str]) -> float:
        num = 0.0
        denom = 0.0
        for e in directional(bundle.evidences):
            w = e.strength * effective_reliability(e, self.tf_weights)
            num += w * sign(e.direction)
            denom += w
        lo, hi = self.cfg["p_up_clip"]
        if denom == 0:
            return HALF
        raw = num / denom  # [-1, 1]
        p_up = HALF + HALF * raw
        p_up = max(float(lo), min(float(hi), p_up))
        reasons.append(f"directional score raw={raw:+.2f} → p_up={p_up:.2f}")
        return p_up

    # -- 2. regime rules (first match wins) ---------------------------------

    def _regime(self, bundle: EvidenceBundle, reasons: list[str]) -> dict[str, float]:
        tf = self.cfg["regime_tf"]
        evs = [e for e in bundle.evidences if e.timeframe.value == tf] or bundle.evidences

        def present(name, direction=None):
            for e in evs:
                if e.name == name and (direction is None or e.direction is direction):
                    return e
            return None

        matched: Regime | None = None
        if present("vol_shock") and self._shock_bearish(evs):
            matched = Regime.CRASH
        elif present("structure_trend", Direction.BULLISH) and present("ema_slope", Direction.BULLISH):
            matched = Regime.TRENDING_UP
        elif present("structure_trend", Direction.BEARISH) and present("ema_slope", Direction.BEARISH):
            matched = Regime.TRENDING_DOWN
        elif present("range_bound") and present("vol_compression"):
            matched = Regime.RANGING
        elif present("vol_compression") and present("bos"):
            matched = Regime.BREAKOUT
        else:
            matched = Regime.RANGING

        reasons.append(f"regime rule → {matched.value}")
        return self._one_hot(matched.value, _REGIMES, float(self.rule["regime_onehot_matched"]))

    @staticmethod
    def _shock_bearish(evs) -> bool:
        for e in evs:
            if e.name == "vol_shock" and e.meta.get("bar_direction") == "down":
                return True
        return False

    # -- 3. behavior rules ---------------------------------------------------

    def _behavior(self, bundle: EvidenceBundle, reasons: list[str]) -> dict[str, float]:
        evs = bundle.evidences

        def d(name, direction):
            e = first_named(evs, name)
            return e is not None and e.direction is direction

        matched: Behavior | None = None
        if d("absorption", Direction.BULLISH) and has_name(evs, "range_bound") and (
            has_name(evs, "large_buys") or has_name(evs, "exchange_outflow")
        ):
            matched = Behavior.ACCUMULATION
        elif d("absorption", Direction.BEARISH) and has_name(evs, "range_bound") and has_name(evs, "large_sells"):
            matched = Behavior.DISTRIBUTION
        elif self._bos_with_volume(evs):
            matched = Behavior.CONTINUATION
        elif has_name(evs, "decoupling") and has_name(evs, "venue_divergence_volume") and self._spoof(evs):
            matched = Behavior.MANIPULATION
        elif d("vol_shock", Direction.NEUTRAL) and has_name(evs, "rsi_oversold") and self._volume_bearish(evs):
            matched = Behavior.CAPITULATION
        elif has_name(evs, "rsi_overbought") and d("funding_extreme", Direction.BEARISH):
            matched = Behavior.EUPHORIA

        if matched is None:
            reasons.append("behavior → unclear (no rule matched)")
            return self._one_hot(Behavior.UNCLEAR.value, _BEHAVIORS,
                                 float(self.rule["behavior_unclear_default"]))
        reasons.append(f"behavior rule → {matched.value}")
        return self._one_hot(matched.value, _BEHAVIORS, float(self.rule["behavior_matched"]))

    @staticmethod
    def _bos_with_volume(evs) -> bool:
        bos = first_named(evs, "bos")
        if bos is None:
            return False
        for vs in named(evs, "volume_spike"):
            if vs.direction is bos.direction:
                return True
        return False

    @staticmethod
    def _spoof(evs) -> bool:
        return any(e.meta.get("spoof_suspect") for e in evs)

    @staticmethod
    def _volume_bearish(evs) -> bool:
        return any(e.name == "volume_spike" and e.direction is Direction.BEARISH for e in evs)

    # -- 4. confidence -------------------------------------------------------

    def _confidence(self, bundle: EvidenceBundle) -> float:
        dirs = directional(bundle.evidences)
        if not dirs:
            return 0.0
        strong = sum(1 for e in dirs if e.strength > float(self.rule["fired_strength_min"]))
        conf = strong / len(dirs)
        return min(conf, float(self.rule["confidence_cap"]))

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _one_hot(matched: str, labels: list[str], matched_prob: float) -> dict[str, float]:
        rest = (1.0 - matched_prob) / (len(labels) - 1)
        return {label: (matched_prob if label == matched else rest) for label in labels}


__all__ = ["RuleEngine"]
