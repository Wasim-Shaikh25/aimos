"""T-013 — anti-lookahead warmup buffer for train/test splits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aimos.core.config import load_params
from aimos.data.live_source import SyntheticSource
from aimos.learning.dataset import build_training_set
from aimos.learning.train import LeakageError, assert_temporal_split, walk_forward_splits
from aimos.observation.runner import required_warmup


def _candles(n: int, seed: int = 0) -> pd.DataFrame:
    return SyntheticSource(seed=seed).fetch("BTC/USDT", "1h", n)


def test_required_warmup_is_at_least_longest_indicator_window():
    params = load_params()
    min_warmup = required_warmup(params)
    cc = params.observation.model_dump()["correlation"]
    assert min_warmup >= int(cc["beta_window"]) + 1


def test_t013_buffer_shorter_than_required_is_rejected():
    params = load_params()
    candles = _candles(500)
    min_warmup = required_warmup(params)
    with pytest.raises(ValueError, match="shorter than required indicator warmup"):
        build_training_set(params, "BTC/USDT", candles, horizon_bars=12, warmup=min_warmup - 1)


def test_t013_buffer_bars_not_in_label_set():
    params = load_params()
    candles = _candles(1000)
    min_warmup = required_warmup(params)
    ds = build_training_set(params, "BTC/USDT", candles, horizon_bars=12, warmup=min_warmup)
    assert ds.n_labeled > 0
    first_ts = ds.timestamps[0]
    assert first_ts >= candles.index[min_warmup]
    # The warmup bar itself is never labeled.
    assert first_ts > candles.index[min_warmup - 1]


def test_t013_first_train_bar_indicator_independent_of_future():
    """The feature at the first train bar must be identical whether the candle
    history stops at that bar or extends into the future. This only holds once
    the warmup buffer is long enough for all indicators to have converged."""
    params = load_params()
    min_warmup = required_warmup(params)
    full = _candles(min_warmup + 100, seed=3)
    truncated = full.iloc[: min_warmup + 12 + 2]
    ds_full = build_training_set(params, "BTC/USDT", full, horizon_bars=12, warmup=min_warmup)
    ds_trunc = build_training_set(params, "BTC/USDT", truncated, horizon_bars=12, warmup=min_warmup)
    assert ds_full.n_labeled > 0 and ds_trunc.n_labeled > 0
    assert np.allclose(ds_full.X[0], ds_trunc.X[0], equal_nan=False)


def test_t013_walk_forward_train_precedes_val():
    params = load_params()
    candles = _candles(1000)
    min_warmup = required_warmup(params)
    ds = build_training_set(params, "BTC/USDT", candles, horizon_bars=12, warmup=min_warmup)
    folds = walk_forward_splits(ds.timestamps, n_folds=3)
    assert folds
    for f in folds:
        train_ts = [ds.timestamps[i] for i in f.train_idx]
        val_ts = [ds.timestamps[i] for i in f.val_idx]
        assert_temporal_split(train_ts, val_ts)  # must not raise
        # Every validation timestamp is strictly after every train timestamp.
        assert max(train_ts) < min(val_ts)
