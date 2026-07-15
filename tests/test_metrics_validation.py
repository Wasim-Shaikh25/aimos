"""Metrics + validation + run-card tests (§9.3, §20.2 — card P4-T8)."""

from __future__ import annotations

import numpy as np
import pytest

from aimos.backtest.metrics import compute_metrics, max_drawdown
from aimos.backtest.report import render_report
from aimos.backtest.validation import (
    config_hash,
    data_hash,
    make_run_card,
    validate_returns,
)


def test_max_drawdown_hand_computed():
    eq = np.array([100.0, 120.0, 90.0, 130.0])
    assert max_drawdown(eq) == pytest.approx((90.0 - 120.0) / 120.0)


def test_metrics_hand_computed():
    eq = [100.0, 110.0, 121.0]  # +10% each step
    m = compute_metrics(eq, trade_r_multiples=[1.5, -1.0, 2.0], n_decisions=10,
                        n_no_trade=7, days=2)
    assert m.total_return == pytest.approx(0.21)
    assert m.hit_rate == pytest.approx(2 / 3)
    assert m.avg_r == pytest.approx((1.5 - 1.0 + 2.0) / 3)
    assert m.no_trade_rate == pytest.approx(0.7)
    assert m.profit_factor == pytest.approx((1.5 + 2.0) / 1.0)


def test_identical_hash_identical_metrics():
    eq = [100.0, 105.0, 103.0, 110.0]
    m1 = compute_metrics(eq, [1.0], 5, 4, days=1)
    m2 = compute_metrics(eq, [1.0], 5, 4, days=1)
    assert m1.to_dict() == m2.to_dict()
    assert data_hash(eq) == data_hash(eq)  # deterministic run-card hash


def test_validation_deterministic_and_gated():
    rng = np.random.default_rng(3)
    rets = list(rng.normal(0.02, 0.01, 200))  # strong positive drift
    v1 = validate_returns(rets, seed=5)
    v2 = validate_returns(rets, seed=5)
    assert v1 == v2  # deterministic
    assert 0.0 <= v1.permutation_p <= 1.0
    assert v1.sharpe_ci_low <= v1.sharpe_ci_high


def test_run_card_and_report_render():
    m = compute_metrics([100.0, 110.0], [1.0], 5, 4, days=1)
    v = validate_returns([0.01, 0.02, -0.01, 0.03], seed=1)
    card = make_run_card("run-1", git_sha="abc123", params_dict={"a": 1},
                         equity_curve=[100.0, 110.0], metrics=m.to_dict(), validation=v)
    assert card.config_hash == config_hash({"a": 1})
    yaml_text = card.to_yaml()
    assert "run-1" in yaml_text
    html = render_report(card, m)
    assert "<html>" in html and "AIMOS Backtest" in html
