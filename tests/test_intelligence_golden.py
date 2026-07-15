"""Golden bundles + partial golden integration (§6, §25.9 — cards P3-T3, P3-T5)."""

from __future__ import annotations

from datetime import datetime, timezone

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
from aimos.intelligence.understand import IntelligenceLayer

TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _il():
    return IntelligenceLayer(load_params())


def _ev(name, direction, s, rel, tf=Timeframe.H1, source=None, meta=None):
    return Evidence(source=source or f"eng.{name}", symbol="SOL", timeframe=tf, timestamp=TS,
                    name=name, value=s, direction=direction, strength=s, reliability=rel, meta=meta or {})


def _bundle(evs):
    return EvidenceBundle(symbol="SOL", timestamp=TS, evidences=evs)


# ---- 5 canonical golden bundles (P3-T3 DoD) ----

def _clear_bull():
    # Strongly bullish but NOT unanimous — a minor pullback signal keeps the rule
    # engine off its 0.95 saturation so rule/bayes agree (as §25.9 itself does).
    # An all-one-direction bundle makes rule saturate while bayes stays moderate,
    # which the fusion reads as disagreement — realistic clear cases aren't unanimous.
    return _bundle([
        _ev("structure_trend", Direction.BULLISH, 0.8, 0.65, source="pa.st",
            meta={"key_levels": {"swing_lows": [146.8], "swing_highs": [153.2]}}),
        _ev("bos", Direction.BULLISH, 0.7, 0.65, source="pa.bos"),
        _ev("ema_slope", Direction.BULLISH, 0.7, 0.55, source="mom.ema"),
        _ev("volume_spike", Direction.BULLISH, 0.7, 0.6, Timeframe.M5, source="vol.vs"),
        _ev("rsi_overbought", Direction.BEARISH, 0.45, 0.55, source="mom.rsi"),
    ])


def _clear_bear():
    return _bundle([
        _ev("structure_trend", Direction.BEARISH, 0.8, 0.65, source="pa.st"),
        _ev("bos", Direction.BEARISH, 0.7, 0.65, source="pa.bos"),
        _ev("ema_slope", Direction.BEARISH, 0.7, 0.55, source="mom.ema"),
        _ev("volume_spike", Direction.BEARISH, 0.7, 0.6, Timeframe.M5, source="vol.vs"),
    ])


def _crash():
    return _bundle([
        _ev("vol_shock", Direction.NEUTRAL, 0.95, 0.55, source="vol.shk",
            meta={"bar_direction": "down", "risk_gate": True}),
        _ev("structure_trend", Direction.BEARISH, 0.8, 0.65, source="pa.st"),
        _ev("rsi_oversold", Direction.BULLISH, 0.6, 0.55, source="mom.rsi"),
    ])


def _illiquid_bull():
    return _bundle([
        _ev("structure_trend", Direction.BULLISH, 0.8, 0.65, source="pa.st"),
        _ev("bos", Direction.BULLISH, 0.7, 0.65, source="pa.bos"),
        _ev("thin_book", Direction.NEUTRAL, 0.8, 0.6, Timeframe.M1, source="liq.tb",
            meta={"risk_gate": True}),
    ])


def _conflict():
    return _bundle([
        _ev("structure_trend", Direction.BULLISH, 0.75, 0.65, source="pa.st"),
        _ev("news_tone", Direction.BULLISH, 0.7, 0.4, source="sent.nt"),
        _ev("book_imbalance", Direction.BEARISH, 0.7, 0.5, Timeframe.M5, source="ob.bi"),
        _ev("thin_book", Direction.NEUTRAL, 0.7, 0.6, Timeframe.M1, source="liq.tb"),
    ])


def test_clear_bull_bullish():
    mu = _il().understand(_clear_bull(), engines_reporting=9)
    assert mu.p_up > 0.7
    assert mu.direction_bias is Direction.BULLISH
    assert mu.regime is Regime.TRENDING_UP


def test_clear_bear_bearish():
    mu = _il().understand(_clear_bear(), engines_reporting=9)
    assert mu.p_up < 0.3
    assert mu.direction_bias is Direction.BEARISH
    assert mu.regime is Regime.TRENDING_DOWN


def test_crash_regime_and_high_risk():
    il = _il()
    mu = il.understand(_crash(), engines_reporting=9)
    assert mu.regime is Regime.CRASH
    # crash regime (100) + vol_shock-floored vol component elevate risk well above
    # a calm bundle, though event/portfolio inputs are absent in isolated L2.
    assert mu.risk_score > 45
    assert mu.risk_score > il.understand(_clear_bull(), engines_reporting=9).risk_score


def test_conflict_confidence_below_clear():
    il = _il()
    clear = il.understand(_clear_bull(), engines_reporting=9)
    conflict = il.understand(_conflict(), engines_reporting=9)
    assert conflict.confidence < clear.confidence


def test_illiquid_confidence_below_clear():
    il = _il()
    clear = il.understand(_clear_bull(), engines_reporting=9)
    illiquid = il.understand(_illiquid_bull(), engines_reporting=9)
    # poor-liquidity penalty cuts conviction even though evidence agrees
    assert illiquid.confidence < clear.confidence


# ---- partial golden integration (§25.9 steps 1-6, P3-T5) ----

def _golden_2519_bundle():
    """A fully-specified bundle approximating the abridged §25.9 evidence."""
    return _bundle([
        _ev("structure_trend", Direction.BULLISH, 0.75, 0.65, source="price_action.st",
            meta={"key_levels": {"swing_lows": [146.8], "swing_highs": [153.2], "atr": 2.1}}),
        _ev("bos", Direction.BULLISH, 0.60, 0.65, source="price_action.bos"),
        _ev("ema_slope", Direction.BULLISH, 0.50, 0.55, source="momentum.ema"),
        _ev("volume_spike", Direction.BULLISH, 0.55, 0.60, Timeframe.M5, source="volume.vs"),
        _ev("book_imbalance", Direction.BULLISH, 0.30, 0.50, Timeframe.M5, source="orderbook.bi"),
        _ev("rsi_overbought", Direction.BEARISH, 0.50, 0.55, source="momentum.rsi"),
    ])


def test_golden_partial_pipeline():
    mu = _il().understand(_golden_2519_bundle(), engines_reporting=9)
    # §25.9 targets: regime TRENDING_UP, behavior CONTINUATION, bias BULLISH
    assert mu.regime is Regime.TRENDING_UP
    assert mu.behavior is Behavior.CONTINUATION
    assert mu.direction_bias is Direction.BULLISH
    # regime_certainty 0.7 (rule-driven), p_up bullish, scores in valid ranges
    assert max(mu.regime_probs.values()) == pytest.approx(0.7)
    assert 0.7 < mu.p_up < 0.9
    assert 0 <= mu.coin_health <= 100
    assert 0 <= mu.risk_score <= 100
    assert 0 <= mu.opportunity_score <= 100
    # key_levels flow through from observation
    assert mu.key_levels.get("swing_lows") == [146.8]
    # engine votes recorded
    assert set(mu.engine_votes) == {"rule", "bayes", "ml"}
    assert mu.engine_votes["ml"] == 0.5  # inert
