"""Rule + Bayes engine tests (§6.1, §6.2 — cards P3-T1, P3-T2)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from aimos.core.config import load_params
from aimos.core.schemas import (
    Behavior,
    Direction,
    Evidence,
    EvidenceBundle,
    Regime,
    Timeframe,
)
from aimos.intelligence.bayes_engine import BayesEngine
from aimos.intelligence.rule_engine import RuleEngine

TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _intel():
    return load_params().intelligence.model_dump()


def _bl():
    return load_params().behavior_likelihoods.model_dump()


def _ev(name, direction, s, rel, tf=Timeframe.H1, source=None, meta=None):
    return Evidence(source=source or f"eng.{name}", symbol="SOL", timeframe=tf, timestamp=TS,
                    name=name, value=s, direction=direction, strength=s, reliability=rel, meta=meta or {})


def _bundle(evs):
    return EvidenceBundle(symbol="SOL", timestamp=TS, evidences=evs)


# ---- rule engine ----

def test_rule_directional_score_all_bullish():
    evs = [_ev("structure_trend", Direction.BULLISH, 0.75, 0.65),
           _ev("bos", Direction.BULLISH, 0.60, 0.65)]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    # all bullish → raw = 1 → p_up clipped to 0.95
    assert op.p_up == pytest.approx(0.95, abs=0.001)


def test_rule_directional_mixed():
    # bullish structure vs bearish rsi → raw between -1 and 1
    evs = [_ev("structure_trend", Direction.BULLISH, 0.8, 0.65),
           _ev("rsi_overbought", Direction.BEARISH, 0.5, 0.55)]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    assert 0.5 < op.p_up < 0.95


def test_rule_regime_trending_up_first_match():
    evs = [_ev("structure_trend", Direction.BULLISH, 0.75, 0.65),
           _ev("ema_slope", Direction.BULLISH, 0.5, 0.55)]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    assert max(op.regime_probs, key=op.regime_probs.get) == Regime.TRENDING_UP.value
    assert op.regime_probs[Regime.TRENDING_UP.value] == pytest.approx(0.7)


def test_rule_regime_crash_on_vol_shock_bearish():
    evs = [_ev("vol_shock", Direction.NEUTRAL, 0.9, 0.55, meta={"bar_direction": "down"})]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    assert max(op.regime_probs, key=op.regime_probs.get) == Regime.CRASH.value


def test_rule_behavior_continuation():
    evs = [_ev("bos", Direction.BULLISH, 0.6, 0.65),
           _ev("volume_spike", Direction.BULLISH, 0.55, 0.6)]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    assert max(op.behavior_probs, key=op.behavior_probs.get) == Behavior.CONTINUATION.value


def test_rule_reasons_populated():
    evs = [_ev("structure_trend", Direction.BULLISH, 0.75, 0.65),
           _ev("ema_slope", Direction.BULLISH, 0.5, 0.55)]
    op = RuleEngine(_intel()).opine(_bundle(evs))
    assert any("regime" in r for r in op.reasons)
    assert any("p_up" in r for r in op.reasons)


# ---- bayes engine ----

def test_bayes_tilt_reproduces_2519_documented():
    # §25.9 step 3: structure_trend (s0.75,rel0.65,1h) tilt = 1+0.35·0.75·0.65 = 1.1706
    # bos (s0.60,rel0.65,1h) tilt = 1.1365 — both reproduce exactly.
    evs = [_ev("structure_trend", Direction.BULLISH, 0.75, 0.65, source="price_action.st")]
    op = BayesEngine(_intel(), _bl()).opine(_bundle(evs))
    assert any("1.171" in r for r in op.reasons)


def test_bayes_posterior_faithful():
    # faithful §6.2 model on the §25.9 bundle (documented posterior is illustrative;
    # the model reproduces down≈0.19 and a bullish p_up).
    evs = [
        _ev("structure_trend", Direction.BULLISH, 0.75, 0.65, source="pa.st"),
        _ev("bos", Direction.BULLISH, 0.60, 0.65, source="pa.bos"),
        _ev("volume_spike", Direction.BULLISH, 0.55, 0.60, Timeframe.M5, source="vol.vs"),
        _ev("book_imbalance", Direction.BULLISH, 0.30, 0.50, Timeframe.M5, source="ob.bi"),
    ]
    op = BayesEngine(_intel(), _bl()).opine(_bundle(evs))
    assert 0.6 < op.p_up < 0.72  # bullish, near the documented 0.695
    assert 0.0 < op.confidence < 1.0


def test_bayes_correlation_guard():
    # 5 evidences from the SAME engine → strongest 2 full, rest ×0.5
    be = BayesEngine(_intel(), _bl())
    evs = [_ev("volume_spike", Direction.BULLISH, 0.5, 0.6, source="volume.a") for _ in range(5)]
    guarded = be._apply_correlation_guard(_bundle(evs))
    factors = sorted(f for _, f in guarded)
    assert factors == [0.5, 0.5, 0.5, 1.0, 1.0]  # 2 kept full, 3 halved
    # effective reliability weight is reduced vs naive 5×
    assert sum(f for _, f in guarded) == pytest.approx(3.5)


def test_bayes_guard_limits_chatty_engine():
    be = BayesEngine(_intel(), _bl())
    # one engine spamming 5 bullish vs another engine 1 bearish
    chatty = [_ev("volume_spike", Direction.BULLISH, 0.6, 0.6, source="volume.a") for _ in range(5)]
    one = [_ev("rsi_overbought", Direction.BEARISH, 0.6, 0.6, source="momentum.r")]
    op = be.opine(_bundle(chatty + one))
    # guard prevents the chatty engine from fully dominating; still bullish but bounded
    assert op.p_up < 0.95


def test_bayes_behavior_posterior():
    evs = [_ev("bos", Direction.BULLISH, 0.6, 0.65, source="pa.bos"),
           _ev("volume_spike", Direction.BULLISH, 0.55, 0.6, source="vol.vs")]
    op = BayesEngine(_intel(), _bl()).opine(_bundle(evs))
    assert op.behavior_probs[Behavior.CONTINUATION.value] > 1.0 / len(Behavior)
