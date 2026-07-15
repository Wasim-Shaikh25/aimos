"""ML training pipeline — walk-forward + leakage guard + shadow ladder (§6.3,
§8.3, card P6-T1).

Validation is WALK-FORWARD ONLY: train on months 1..k, validate month k+1, roll.
A random split is a leakage bug — ``assert_temporal_split`` is the forbidden-path
guard. Retraining is a manual command; no auto-deployment. The ML fusion weight
stays 0 (shadow) until a human raises it in config after the shadow window holds
(§8.3). LightGBM is an optional [ml] dep — the model is pluggable so the pipeline
and its guards are testable without it. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import numpy as np

from aimos.learning.model import LogisticModel, auc, fit_logistic


class LeakageError(AssertionError):
    """Raised when a split would leak future information (§9.1, §13)."""


@dataclass
class Fold:
    train_idx: np.ndarray
    val_idx: np.ndarray


def walk_forward_splits(timestamps: Sequence[datetime], n_folds: int = 3) -> list[Fold]:
    """Rolling temporal folds: train on the past, validate the next block (§6.3).

    Sorted by time; block ``k`` validates on data strictly after all of its
    training data — never a random shuffle.
    """
    order = np.argsort([t.timestamp() for t in timestamps])
    n = len(order)
    if n < n_folds + 1:
        return []
    block = n // (n_folds + 1)
    folds: list[Fold] = []
    for k in range(1, n_folds + 1):
        train = order[: k * block]
        val = order[k * block : (k + 1) * block]
        if len(val) == 0:
            break
        folds.append(Fold(train, val))
    return folds


def assert_temporal_split(train_ts: Sequence[datetime], val_ts: Sequence[datetime]) -> None:
    """Forbidden-path guard: every validation timestamp must be AFTER all training
    timestamps. A random split trips this (leakage), a walk-forward split passes."""
    if not train_ts or not val_ts:
        return
    latest_train = max(t.timestamp() for t in train_ts)
    earliest_val = min(t.timestamp() for t in val_ts)
    if earliest_val <= latest_train:
        raise LeakageError(
            "validation data overlaps/precedes training data — random split forbidden (§6.3)"
        )


def shadow_weight(config_ml_weight: float) -> float:
    """The ML fusion weight in effect. Stays 0 (shadow) until config raises it (§8.3)."""
    return max(0.0, float(config_ml_weight))


@dataclass
class PromotionChecklist:
    val_auc: float
    brier_improves: bool
    shadow_weeks_held: int

    def passes(self, auc_min: float, shadow_weeks_required: int) -> bool:
        return (
            self.val_auc > auc_min
            and self.brier_improves
            and self.shadow_weeks_held >= shadow_weeks_required
        )


def train_model(
    X: np.ndarray, y: Sequence[int], timestamps: Sequence[datetime], n_folds: int = 3
) -> LogisticModel:
    """Walk-forward validate then fit the final model on all data (§6.3).

    Returns a real ``LogisticModel`` whose ``val_auc`` is the mean out-of-sample
    AUC across the rolling folds — never a random split (each fold's guard runs).
    """
    X = np.atleast_2d(np.asarray(X, dtype=float))
    y = np.asarray(list(y), dtype=int)
    folds = walk_forward_splits(timestamps, n_folds=n_folds)
    aucs: list[float] = []
    for f in folds:
        assert_temporal_split([timestamps[i] for i in f.train_idx],
                              [timestamps[i] for i in f.val_idx])
        if len(set(y[f.train_idx])) < 2:
            continue
        m = fit_logistic(X[f.train_idx], y[f.train_idx])
        scores = m.predict_proba(X[f.val_idx])
        aucs.append(auc(scores, y[f.val_idx]))
    final = fit_logistic(X, y)
    final.val_auc = float(np.mean(aucs)) if aucs else 0.5
    return final


__all__ = [
    "Fold",
    "LeakageError",
    "PromotionChecklist",
    "assert_temporal_split",
    "shadow_weight",
    "train_model",
    "walk_forward_splits",
]
