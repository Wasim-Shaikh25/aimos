"""Fusion + confidence tests (§6.4, §6.7 — card P3-T3).

The §25.9 step-5 fusion numbers reproduce EXACTLY from the documented opinions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import (
    Behavior,
    Direction,
    EngineOpinion,
    Evidence,
    EvidenceBundle,
    Timeframe,
)
from aimos.intelligence.confidence import compute_confidence, evidence_coverage
from aimos.intelligence.fusion import FusionEngine

TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _intel():
    return load_params().intelligence.model_dump()


def _fusion():
    return FusionEngine(_intel())


def _bundle(evidences=None):
    return EvidenceBundle(symbol="SOL", timestamp=TS, evidences=evidences or [])


def _ev(name, direction, s=0.5, rel=0.5, tf=Timeframe.H1, value=None, meta=None):
    return Evidence(source=f"e.{name}", symbol="SOL", timeframe=tf, timestamp=TS,
                    name=name, value=value if value is not None else s, direction=direction,
                    strength=s, reliability=rel, meta=meta or {})


def test_fusion_reproduces_2519_step5():
    # documented engine opinions from §25.9
    rule = EngineOpinion(engine="rule", p_up=0.81, confidence=0.66)
    bayes = EngineOpinion(engine="bayes", p_up=0.695, confidence=0.41)
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    res = _fusion().fuse([rule, bayes, ml], _bundle())
    assert res.p_up == pytest.approx(0.766, abs=0.001)
    assert res.disagreement == pytest.approx(0.115, abs=0.001)
    assert res.penalty_mult == 1.0  # no conflict penalties fire
    assert res.direction_bias is Direction.BULLISH


def test_confidence_reproduces_2519():
    conf = compute_confidence(disagreement=0.115, coverage=9 / 13, regime_certainty=0.7, penalty_mult=1.0)
    assert conf == pytest.approx(0.428, abs=0.001)


def test_evidence_coverage():
    assert evidence_coverage(9, 13) == pytest.approx(9 / 13)
    assert evidence_coverage(13, 13) == 1.0
    assert evidence_coverage(0, 13) == 0.0


def test_direction_thresholds():
    fe = _fusion()
    assert fe._bias(0.58) is Direction.BULLISH
    assert fe._bias(0.42) is Direction.BEARISH
    assert fe._bias(0.50) is Direction.NEUTRAL


def test_disagreement_penalty_fires():
    rule = EngineOpinion(engine="rule", p_up=0.85, confidence=0.6)
    bayes = EngineOpinion(engine="bayes", p_up=0.45, confidence=0.6)  # |0.4| > 0.25
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    res = _fusion().fuse([rule, bayes, ml], _bundle())
    assert res.disagreement > 0.25
    assert res.penalty_mult == pytest.approx(0.6)  # disagreement_conf_mult
    assert "engines disagree" in res.reasons


def test_headline_shock_pulls_p_up_and_cuts_confidence():
    rule = EngineOpinion(engine="rule", p_up=0.90, confidence=0.6)
    bayes = EngineOpinion(engine="bayes", p_up=0.88, confidence=0.6)
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    bundle = _bundle([_ev("headline_shock", Direction.BEARISH, s=1.0, meta={"risk_gate": True})])
    res = _fusion().fuse([rule, bayes, ml], bundle)
    # p_up pulled 50% toward 0.5 from ~0.89 → ~0.695
    assert res.p_up < 0.80
    assert res.penalty_mult == pytest.approx(0.5)  # headline_shock_conf_mult
    assert "headline shock" in res.reasons


def test_poor_liquidity_penalty():
    rule = EngineOpinion(engine="rule", p_up=0.7, confidence=0.6)
    bayes = EngineOpinion(engine="bayes", p_up=0.68, confidence=0.6)
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    bundle = _bundle([_ev("thin_book", Direction.NEUTRAL, s=0.5, meta={"risk_gate": True})])
    res = _fusion().fuse([rule, bayes, ml], bundle)
    assert res.penalty_mult == pytest.approx(0.7)  # liquidity_conf_mult
    assert "poor liquidity" in res.reasons


def test_penalty_ordering_multiplies():
    # both disagreement AND headline_shock → penalties multiply (0.6 × 0.5)
    rule = EngineOpinion(engine="rule", p_up=0.85, confidence=0.6)
    bayes = EngineOpinion(engine="bayes", p_up=0.45, confidence=0.6)
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    bundle = _bundle([_ev("headline_shock", Direction.BEARISH, s=1.0)])
    res = _fusion().fuse([rule, bayes, ml], bundle)
    assert res.penalty_mult == pytest.approx(0.6 * 0.5)


def test_sentiment_book_conflict_shifts_unclear():
    rule = EngineOpinion(engine="rule", p_up=0.6, confidence=0.6,
                         behavior_probs={b.value: 1.0 / len(Behavior) for b in Behavior})
    bayes = EngineOpinion(engine="bayes", p_up=0.6, confidence=0.6,
                          behavior_probs={b.value: 1.0 / len(Behavior) for b in Behavior})
    ml = EngineOpinion(engine="ml", p_up=0.5, confidence=0.0)
    bundle = _bundle([
        _ev("news_tone", Direction.BULLISH, s=0.5),
        _ev("book_imbalance", Direction.BEARISH, s=0.5),
    ])
    res = _fusion().fuse([rule, bayes, ml], bundle)
    assert "mixed evidence: sentiment vs order book" in res.reasons
    # UNCLEAR mass increased
    assert res.behavior_probs[Behavior.UNCLEAR.value] > 1.0 / len(Behavior)
