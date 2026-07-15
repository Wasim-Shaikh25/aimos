"""A real, self-contained classifier for the ML engine (§6.3, card P6-T1).

Pure-numpy L2-regularized logistic regression (gradient descent) so the ML engine
genuinely LEARNS and PREDICTS — no LightGBM dependency required to be functional
(LightGBM is an optional upgrade). Fit / predict_proba / save / load (JSON
artifact). Standardizes features with the training mean/std. Not in the linted
layers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class LogisticModel:
    weights: np.ndarray
    bias: float
    mean: np.ndarray
    std: np.ndarray
    val_auc: float = 0.5
    n_features: int = 0

    # -- inference ----------------------------------------------------------

    def _z(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / np.where(self.std == 0, 1.0, self.std)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        logits = self._z(X) @ self.weights + self.bias
        return 1.0 / (1.0 + np.exp(-logits))

    def predict_one(self, x: np.ndarray) -> float:
        return float(self.predict_proba(np.asarray(x, dtype=float).reshape(1, -1))[0])

    # -- persistence --------------------------------------------------------

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "weights": self.weights.tolist(), "bias": self.bias,
            "mean": self.mean.tolist(), "std": self.std.tolist(),
            "val_auc": self.val_auc, "n_features": self.n_features,
        }), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: Path | str) -> "LogisticModel":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            weights=np.asarray(d["weights"], dtype=float), bias=float(d["bias"]),
            mean=np.asarray(d["mean"], dtype=float), std=np.asarray(d["std"], dtype=float),
            val_auc=float(d.get("val_auc", 0.5)), n_features=int(d.get("n_features", 0)),
        )


def fit_logistic(
    X: np.ndarray, y: np.ndarray, l2: float = 1e-3, lr: float = 0.1, epochs: int = 500
) -> LogisticModel:
    """Fit L2 logistic regression by gradient descent (deterministic)."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    y = np.asarray(y, dtype=float)
    n, d = X.shape
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    Xz = (X - mean) / np.where(std == 0, 1.0, std)
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(Xz @ w + b)))
        err = p - y
        grad_w = Xz.T @ err / n + l2 * w
        grad_b = float(err.mean())
        w -= lr * grad_w
        b -= lr * grad_b
    return LogisticModel(weights=w, bias=b, mean=mean, std=std, n_features=d)


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """ROC-AUC via the rank-sum (Mann–Whitney) identity."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    pos = s[y == 1]
    neg = s[y == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.5
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, s.size + 1)
    rank_pos = ranks[y == 1].sum()
    return float((rank_pos - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


__all__ = ["LogisticModel", "auc", "fit_logistic"]
