"""History-training pipeline: dataset build, feature parity, and the CLI gate.

Covers the "train the ML on older data via paper replay" path — the dataset
builder, train/serve feature parity, and the enable/disable switch on
scripts/train_from_history.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from aimos.core.config import load_params
from aimos.data.live_source import SyntheticSource
from aimos.learning.dataset import build_training_set
from aimos.learning.features import feature_names
from aimos.learning.train import train_model


@pytest.fixture(scope="module")
def params():
    return load_params()


@pytest.fixture(scope="module")
def candles():
    return SyntheticSource(seed=7).fetch("BTC/USDT", "1h", 800)


def test_dataset_shape_and_labels(params, candles):
    ds = build_training_set(params, "BTC/USDT", candles, horizon_bars=12, warmup=100)
    assert ds.n_labeled > 0
    assert ds.width == len(feature_names()) == 70
    assert set(ds.y) <= {0, 1}
    assert ds.X.shape == (ds.n_labeled, 70)
    assert np.isfinite(ds.X).all()


def test_feature_vector_matches_inference_construction(params, candles):
    """The trainer's features must be byte-identical to what the ML engine sees."""
    from aimos.core.clock import BacktestClock
    from aimos.core.schemas import Timeframe
    from aimos.data.context import build_context
    from aimos.intelligence.understand import IntelligenceLayer
    from aimos.learning.features import feature_vector
    from aimos.observation.runner import build_engines, run_all

    clock = BacktestClock()
    t = candles.index[300].to_pydatetime()
    clock.set(t)
    intel = IntelligenceLayer(params)
    bundle = run_all(build_engines(params, clock),
                     build_context("BTC/USDT", t, {Timeframe.H1: candles.iloc[:301]},
                                   peers={"BTC": candles.iloc[:301]}))
    # ml_feature_vector reproduces understand()'s exact args (rule regime, atr_pct, rel_vol=0)
    rule_regime = intel._argmax_regime(intel.rule.opine(bundle).regime_probs)
    kl = intel._key_levels(bundle)
    atr, price = float(kl.get("atr", 0.0)), float(kl.get("price", 0.0))
    atr_pct = atr / price * 100.0 if price > 0 else 0.0
    expected = feature_vector(bundle, regime=rule_regime, atr_pct=atr_pct, rel_vol=0.0)
    assert np.array_equal(intel.ml_feature_vector(bundle), expected)


def test_trained_model_roundtrips(params, candles, tmp_path):
    ds = build_training_set(params, "BTC/USDT", candles, horizon_bars=12, warmup=100)
    model = train_model(ds.X, ds.y, ds.timestamps, n_folds=3)
    assert model.n_features == 70
    assert 0.0 <= model.val_auc <= 1.0
    p = model.save(tmp_path / "m.json")
    from aimos.learning.model import LogisticModel
    loaded = LogisticModel.load(p)
    assert loaded.n_features == 70
    assert loaded.val_auc == pytest.approx(model.val_auc)


def test_cli_disabled_by_default(monkeypatch):
    """The enable/disable switch: off → the script refuses and exits 3."""
    monkeypatch.delenv("AIMOS__LEARNING__HISTORY__ENABLED", raising=False)
    from scripts.train_from_history import main
    assert main(["--synthetic", "--symbol", "BTC/USDT"]) == 3


def test_cli_enabled_trains_and_saves(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMOS__LEARNING__HISTORY__ENABLED", "true")
    monkeypatch.setenv("AIMOS__LEARNING__ML__MIN_LABELED_SAMPLES", "50")
    monkeypatch.setenv("AIMOS__LEARNING__HISTORY__HORIZON_BARS", "12")
    monkeypatch.setenv("AIMOS__LEARNING__HISTORY__WARMUP", "100")
    out = tmp_path / "ml.json"
    from scripts.train_from_history import main
    rc = main(["--synthetic", "--symbol", "BTC/USDT", "--bars", "700", "--out", str(out)])
    assert rc in (0, 1)  # 0 = passed AUC gate, 1 = trained but below gate — both save
    assert out.exists()
