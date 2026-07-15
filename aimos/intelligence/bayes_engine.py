"""Bayesian engine (§6.2, card P3-T2).

Sequential log-space belief updating over H = {up, down, flat}. Each directional
evidence tilts the likelihoods by ``1 + lift·strength·eff_reliability`` (eff =
tf-adjusted, §25.2). A correlation guard halves the reliability of same-engine
evidences beyond the strongest N (default 2), so one chatty engine cannot
dominate. Engine confidence = 1 − normalized entropy of the posterior.

Behavior posterior: a separate categorical over behaviors, updated from the
``behavior_likelihoods.yaml`` table (§6.2). Regime is rule-driven; SPEC-GAP: the
spec gives no per-regime likelihood table for bayes, so bayes returns a uniform
regime distribution and defers regime to the rule engine in fusion.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

import numpy as np

from aimos.core.normalize import HALF
from aimos.core.schemas import (
    Behavior,
    Direction,
    EngineOpinion,
    EvidenceBundle,
    Regime,
)
from aimos.intelligence.base import effective_reliability

_BEHAVIORS = [b.value for b in Behavior]
_REGIMES = [r.value for r in Regime]
_UP, _DOWN, _FLAT = 0, 1, 2


class BayesEngine:
    def __init__(self, cfg: Mapping[str, Any], behavior_likelihoods: Mapping[str, Any]) -> None:
        self.cfg = cfg  # params.intelligence subtree
        self.tf_weights = cfg["tf_weights"]
        self.lift = float(cfg["bayes_likelihood_lift"])
        self.keep = int(cfg["correlation_guard_keep"])
        self.bl = behavior_likelihoods

    def opine(self, bundle: EvidenceBundle) -> EngineOpinion:
        guarded = self._apply_correlation_guard(bundle)
        post, reasons = self._update(guarded)
        p_up = float(post[_UP] + HALF * post[_FLAT])
        confidence = self._entropy_confidence(post)
        behavior_probs = self._behavior_posterior(bundle)
        # SPEC-GAP (§6.2): the spec gives no per-regime likelihood table for
        # bayes, so bayes ABSTAINS from regime — it returns an empty regime dist
        # and fusion's regime is rule-driven (fusion skips empty distributions).
        regime_probs: dict[str, float] = {}
        return EngineOpinion(
            engine="bayes",
            p_up=p_up,
            regime_probs=regime_probs,
            behavior_probs=behavior_probs,
            confidence=confidence,
            reasons=reasons,
        )

    # -- correlation guard (§6.2) -------------------------------------------

    def _apply_correlation_guard(self, bundle: EvidenceBundle) -> list[tuple]:
        """Return (evidence, reliability_factor) with same-engine tail halved."""
        by_engine: dict[str, list] = defaultdict(list)
        for e in bundle.evidences:
            engine = e.source.split(".")[0]
            by_engine[engine].append(e)
        out: list[tuple] = []
        for engine, evs in by_engine.items():
            ranked = sorted(evs, key=lambda e: e.strength * e.reliability, reverse=True)
            for i, e in enumerate(ranked):
                factor = 1.0 if i < self.keep else HALF
                out.append((e, factor))
        return out

    # -- posterior update ----------------------------------------------------

    def _update(self, guarded: list[tuple]) -> tuple[np.ndarray, list[str]]:
        prior = np.array(self.cfg["bayes_prior"], dtype=float)
        log_post = np.log(prior)
        reasons: list[str] = []
        for e, factor in guarded:
            if e.direction is Direction.NEUTRAL:
                continue
            eff_rel = effective_reliability(e, self.tf_weights) * factor
            tilt = 1.0 + self.lift * e.strength * eff_rel
            lik = np.ones(prior.size)
            if e.direction is Direction.BULLISH:
                lik[_UP], lik[_DOWN] = tilt, 1.0 / tilt
            else:
                lik[_DOWN], lik[_UP] = tilt, 1.0 / tilt
            log_post += np.log(lik)
            reasons.append(f"{e.name}({e.direction.value}, s={e.strength:.2f}) tilt {tilt:.3f}")
        post = np.exp(log_post - log_post.max())
        post /= post.sum()
        return post, reasons

    def _entropy_confidence(self, post: np.ndarray) -> float:
        p = np.clip(post, 1e-12, 1.0)  # noqa: magic — numerical-stability epsilon
        entropy = float(-(p * np.log(p)).sum())
        max_entropy = float(np.log(len(post)))
        return max(0.0, min(1.0, 1.0 - entropy / max_entropy))

    # -- behavior posterior --------------------------------------------------

    def _behavior_posterior(self, bundle: EvidenceBundle) -> dict[str, float]:
        default_tilt = float(self.bl["default_tilt"])
        supports: Mapping[str, list] = self.bl.get("supports", {})
        log_post = {b: 0.0 for b in _BEHAVIORS}
        for e in bundle.evidences:
            for behavior in supports.get(e.name, []):
                if behavior in log_post:
                    log_post[behavior] += float(np.log(default_tilt)) * e.strength
        vals = np.array([log_post[b] for b in _BEHAVIORS])
        exp = np.exp(vals - vals.max())
        exp /= exp.sum()
        return {b: float(exp[i]) for i, b in enumerate(_BEHAVIORS)}


__all__ = ["BayesEngine"]
