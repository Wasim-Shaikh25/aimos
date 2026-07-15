"""ML pipeline + calibration + drift + optimizer tests (§6.3, §8.3, §8.4, §21.4,
§23.7 — cards P6-T1, P6-T2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Direction, Evidence, EvidenceBundle, Regime, Timeframe
from aimos.learning.calibration import (
    brier_score,
    isotonic_fit,
    population_stability_index,
    recalibrate_reliability,
)
from aimos.learning.features import feature_names, feature_vector
from aimos.learning.optimize import ConfigWriteForbidden, OptimizationProposal, pick_plateau
from aimos.learning.train import (
    LeakageError,
    assert_temporal_split,
    shadow_weight,
    walk_forward_splits,
)

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---- feature builder (P6-T1) ----

def test_feature_vector_stable_width():
    b = EvidenceBundle(symbol="SOL", timestamp=TS, evidences=[
        Evidence(source="e.volume_spike", symbol="SOL", timeframe=Timeframe.H1, timestamp=TS,
                 name="volume_spike", value=0.6, direction=Direction.BULLISH, strength=0.6),
    ])
    vec = feature_vector(b, regime=Regime.TRENDING_UP, atr_pct=2.0, rel_vol=3.0)
    assert len(vec) == len(feature_names())  # fixed width forever (§25.6)
    # volume_spike bullish → +strength at its index
    from aimos.core.evidence_registry import feature_index
    assert vec[feature_index()["volume_spike"]] == pytest.approx(0.6)


# ---- walk-forward + leakage guard (P6-T1) ----

def test_walk_forward_is_temporal():
    ts = [TS + timedelta(days=i) for i in range(40)]
    folds = walk_forward_splits(ts, n_folds=3)
    assert folds
    for f in folds:
        train_ts = [ts[i] for i in f.train_idx]
        val_ts = [ts[i] for i in f.val_idx]
        assert_temporal_split(train_ts, val_ts)  # must not raise


def test_random_split_forbidden_path():
    ts = [TS + timedelta(days=i) for i in range(20)]
    # a random split interleaves future into training → leakage guard fires
    train = ts[::2]
    val = ts[1::2]  # includes timestamps before some training points
    with pytest.raises(LeakageError):
        assert_temporal_split(train, val)


def test_shadow_weight_stays_zero_by_default():
    ml_weight = load_params().intelligence.model_dump()["fusion_weights"]["ml"]
    assert shadow_weight(ml_weight) == 0.0  # inert until a human raises it (§8.3)


# ---- calibration (P6-T1/T2) ----

def test_isotonic_monotonic():
    x = [0.1, 0.2, 0.3, 0.4, 0.5]
    y = [0, 0, 1, 0, 1]  # noisy → isotonic smooths to non-decreasing
    model = isotonic_fit(x, y)
    preds = [model.predict(xi) for xi in x]
    assert all(preds[i] <= preds[i + 1] + 1e-9 for i in range(len(preds) - 1))


def test_recalibrate_reliability_formula():
    # rel_new = clamp(2·hitrate − 0.5, 0.2, 0.9)
    assert recalibrate_reliability(0.7, 0.2, 0.9) == pytest.approx(0.9)  # 0.9 capped
    assert recalibrate_reliability(0.5, 0.2, 0.9) == pytest.approx(0.5)
    assert recalibrate_reliability(0.1, 0.2, 0.9) == pytest.approx(0.2)  # floored


def test_psi_drift_trigger():
    rng = np.random.default_rng(0)
    train = rng.normal(0, 1, 1000)
    same = rng.normal(0, 1, 1000)
    shifted = rng.normal(2, 1, 1000)  # large distribution shift
    assert population_stability_index(train, same) < 0.1
    assert population_stability_index(train, shifted) > 0.25  # drift threshold


def test_brier_score():
    assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


# ---- optimizer proposals only (P6-T2) ----

def test_optimizer_writes_proposal_not_config(tmp_path):
    prop = OptimizationProposal("study1", "oos_sharpe", {"execution.base_risk_pct": 0.3}, "plateau of 5")
    path = prop.write(tmp_path / "proposals")
    assert path.exists() and "proposed_params" in path.read_text()
    # hard rail: never writes under config/
    with pytest.raises(ConfigWriteForbidden):
        prop.write(tmp_path / "config" / "proposals")


def test_pick_plateau_prefers_robust():
    trials = [({"a": 1}, 1.0), ({"a": 2}, 0.98), ({"a": 3}, 0.5)]
    params, note = pick_plateau(trials, tolerance_pct=5.0)
    assert params in ({"a": 1}, {"a": 2})  # within 5% band, not the 0.5 outlier
    assert "within" in note
