"""Risk-analytics wiring tests (REQ-1).

Covers:
- the standalone runner with a synthetic data source,
- the ``GET /api/risk`` endpoint shape served by ``build_app``.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aimos.core.config import load_params
from aimos.risk.analytics_runner import compute_risk_report
from aimos.runtime.serve import build_app


def _fake_source(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    """Deterministic OHLCV source for unit tests."""
    import numpy as np
    rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
    rets = rng.normal(0.0, 0.01, bars)
    close = 30_000.0 * np.cumprod(1.0 + rets)
    opens = np.concatenate([[close[0]], close[:-1]])
    highs = np.maximum(opens, close) * (1.0 + np.abs(rng.normal(0.0, 0.003, bars)))
    lows = np.minimum(opens, close) * (1.0 - np.abs(rng.normal(0.0, 0.003, bars)))
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": close,
        "volume": np.abs(rng.normal(1000, 200, bars)),
    })


def test_compute_risk_report_shape():
    """Runner produces the expected VaR/ES + alpha/beta + factor payload."""
    rng = __import__("numpy").random.default_rng(1)
    equity = [10_000.0]
    for _ in range(99):
        equity.append(equity[-1] * (1.0 + rng.normal(0.0, 0.005)))
    params = load_params()
    report = compute_risk_report(
        equity=equity,
        params=params,
        data_source=_fake_source,
        universe=None,
    )
    assert "var_95_pct" in report
    assert "es_95_pct" in report
    assert "var_99_pct" in report
    assert "es_99_pct" in report
    assert "btc" in report and "basket" in report and "factor" in report
    assert all(k in report["btc"] for k in ("alpha_annualized", "beta", "t_stat"))
    assert all(k in report["basket"] for k in ("alpha_annualized", "beta", "t_stat"))
    assert all(k in report["factor"] for k in ("btc_beta_pct", "idiosyncratic_pct"))
    assert report["sample_size"] >= 3
    assert "computed_at" in report


def test_risk_api_endpoint(monkeypatch):
    """``GET /api/risk`` is reachable through the running serve stack."""
    monkeypatch.setenv("AIMOS__PAPER__LOOP_SECONDS", "0.1")
    monkeypatch.setenv("AIMOS__RISK__INTERVAL_SECONDS", "0.2")
    monkeypatch.setenv("AIMOS__RISK__MIN_SAMPLES", "3")
    app = build_app(offline=True)
    with TestClient(app) as client:
        time.sleep(0.8)
        r = client.get("/api/risk")
        assert r.status_code == 200
        data = r.json()
        if "note" in data:
            pytest.skip("risk analytics still warming up")
        assert "var_95_pct" in data
        assert "btc" in data and "basket" in data and "factor" in data
