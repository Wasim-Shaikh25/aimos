"""Statistical validation + run cards (§20.2, §9.3, card P4-T8).

Wraps the vendored VT validation suite (Monte-Carlo permutation p-value, bootstrap
Sharpe CI) and emits reproducible run cards. Two run cards with identical config/
data hashes must produce identical metrics (extends §13 test 7 to backtests).
Not in the linted layers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import yaml

from vendor.vt_validation import bootstrap_sharpe_ci, permutation_pvalue


@dataclass
class ValidationResult:
    permutation_p: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    passes_promotion_gate: bool  # p<0.05 AND CI low > 0 (§8.3, §17.5)


def validate_returns(returns: Sequence[float], seed: int = 0, alpha: float = 0.05) -> ValidationResult:
    p = permutation_pvalue(returns, seed=seed)
    lo, hi = bootstrap_sharpe_ci(returns, seed=seed, alpha=alpha)
    return ValidationResult(
        permutation_p=p, sharpe_ci_low=lo, sharpe_ci_high=hi,
        passes_promotion_gate=(p < alpha and lo > 0),
    )


def config_hash(params_dict: dict[str, Any]) -> str:
    blob = json.dumps(params_dict, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def data_hash(values: Sequence[float]) -> str:
    blob = json.dumps([round(float(v), 6) for v in values]).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class RunCard:
    run_id: str
    git_sha: str
    config_hash: str
    data_hash: str
    universe_snapshot_id: str
    seed: int
    engine_profile: str
    metrics: dict
    validation: dict

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), sort_keys=True)


def make_run_card(
    run_id: str,
    git_sha: str,
    params_dict: dict,
    equity_curve: Sequence[float],
    metrics: dict,
    validation: ValidationResult,
    seed: int = 0,
    engine_profile: str = "no_book",
    universe_snapshot_id: str = "dev",
) -> RunCard:
    return RunCard(
        run_id=run_id, git_sha=git_sha,
        config_hash=config_hash(params_dict), data_hash=data_hash(equity_curve),
        universe_snapshot_id=universe_snapshot_id, seed=seed, engine_profile=engine_profile,
        metrics=metrics, validation=asdict(validation),
    )


__all__ = ["RunCard", "ValidationResult", "config_hash", "data_hash", "make_run_card", "validate_returns"]
