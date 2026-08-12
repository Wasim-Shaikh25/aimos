"""Build an ML training set from historical candles (§6.3, §8.2-8.3).

Replays the EXACT production observation → intelligence pipeline over older data
(anti-lookahead: each decision sees only bars ≤ t) and labels every scanned bar
with the triple-barrier method over the next ``horizon_bars`` closes. Features come
from ``IntelligenceLayer.ml_feature_vector`` — the same construction used at
inference — so there is no train/serve skew.

This is how you "train in paper trading on older Binance data": the loop is a
paper replay; its labeled decisions become the ML training set. Manual, offline,
and never in the decision path — the trained model stays in shadow (fusion weight
0) until a human promotes it (§8.3). Not in the magic-number-linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from aimos.core.clock import BacktestClock
from aimos.core.schemas import Timeframe
from aimos.data.context import build_context
from aimos.intelligence.understand import IntelligenceLayer
from aimos.learning.features import feature_names
from aimos.learning.labeling import BarrierConfig, triple_barrier_label
from aimos.observation.runner import build_engines, engines_reporting, required_warmup, run_all

_DEF_UPPER, _DEF_LOWER, _DEF_NOISE = 1.5, 1.5, 0.3  # triple-barrier defaults (§8.2)


@dataclass
class TrainingSet:
    X: np.ndarray
    y: list[int] = field(default_factory=list)
    timestamps: list[datetime] = field(default_factory=list)
    n_scanned: int = 0     # bars with usable geometry (atr>0) that got a label attempt
    n_labeled: int = 0     # bars that produced a non-None (non-noise) label

    @property
    def width(self) -> int:
        return self.X.shape[1] if self.X.size else 0


def _barrier_cfg(params) -> BarrierConfig:
    tb = params.model_dump().get("learning", {}).get("triple_barrier", {}) or {}
    return BarrierConfig(
        upper_atr=float(tb.get("upper_atr", _DEF_UPPER)),
        lower_atr=float(tb.get("lower_atr", _DEF_LOWER)),
        noise_atr=float(tb.get("noise_atr", _DEF_NOISE)),
    )


def build_training_set(
    params,
    symbol: str,
    candles: pd.DataFrame,
    horizon_bars: int,
    warmup: Optional[int] = None,
) -> TrainingSet:
    """Replay ``candles`` through observation+intelligence and label each bar.

    Target is ``p_up``: label 1 if price hits +ATR before −ATR within the horizon,
    0 the other way, dropped (noise) if it times out inside the band — the exact
    triple-barrier semantics the calibration path expects. Feature vectors match
    inference via ``IntelligenceLayer.ml_feature_vector``.

    The warmup buffer is sized to the longest indicator lookback so the first
    labeled/traded bar is never part of the indicator warmup (T-013).
    """
    min_warmup = required_warmup(params)
    if warmup is None:
        warmup = min_warmup
    if warmup < min_warmup:
        raise ValueError(f"warmup {warmup} shorter than required indicator warmup {min_warmup} (T-013)")
    n = len(candles)
    if n < warmup + horizon_bars + 2:
        raise ValueError(f"candles {n} shorter than warmup {warmup} + horizon {horizon_bars} + 2 (need a label bar and one future bar)")

    clock = BacktestClock()
    engines = build_engines(params, clock)
    intel = IntelligenceLayer(params)
    coverage = int(params.intelligence.model_dump()["coverage_engines"])
    bcfg = _barrier_cfg(params)
    closes = candles["close"].astype(float).to_numpy()

    rows: list[np.ndarray] = []
    ys: list[int] = []
    ts: list[datetime] = []
    n_scanned = 0
    last = n - horizon_bars - 1  # need horizon_bars of future to label
    for i in range(warmup, last):
        bar_time = candles.index[i].to_pydatetime()
        clock.set(bar_time)
        window = candles.iloc[: i + 1]  # data ≤ t (anti-lookahead, §9.1)
        ctx = build_context(symbol, bar_time, {Timeframe.H1: window}, peers={"BTC": window})
        bundle = run_all(engines, ctx)
        reporting = len(engines_reporting(bundle))
        mu = intel.understand(bundle, reporting, coverage_engines=coverage)
        atr = float(mu.key_levels.get("atr", 0.0))
        price = float(mu.key_levels.get("price", 0.0))
        if atr <= 0 or price <= 0:
            continue
        n_scanned += 1
        future = list(closes[i + 1 : i + 1 + horizon_bars])
        label = triple_barrier_label(price, atr, future, bcfg, long=True)
        if label is None:
            continue  # timed out in the noise band → not a training example
        rows.append(intel.ml_feature_vector(bundle))
        ys.append(int(label))
        ts.append(bar_time)

    width = len(feature_names())
    X = np.atleast_2d(np.asarray(rows, dtype=float)) if rows else np.zeros((0, width))
    return TrainingSet(X=X, y=ys, timestamps=ts, n_scanned=n_scanned, n_labeled=len(ys))


__all__ = ["TrainingSet", "build_training_set"]
