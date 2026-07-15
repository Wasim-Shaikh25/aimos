"""Vendor package smoke tests (§22 — card P15-T4 DoD).

Each vendor package must import under ``vendor.*`` and its reference math must be
sane. The import-linter contract blocking ``vendor.vt_research`` from the runtime
is verified in ``test_lints.py`` (lint-imports) and asserted structurally here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_vendor_packages_import():
    import vendor  # noqa: F401
    import vendor.ft_protections  # noqa: F401
    import vendor.hb_mm  # noqa: F401
    import vendor.jesse_engine  # noqa: F401
    import vendor.vt_factors  # noqa: F401
    import vendor.vt_validation  # noqa: F401


def test_hb_mm_avellaneda_stoikov_math():
    from vendor.hb_mm import optimal_spread, quote_prices, reservation_price

    # long inventory skews reservation price below mid
    r = reservation_price(mid=100.0, inventory=5.0, gamma=0.1, sigma=2.0, time_to_horizon=1.0)
    assert r < 100.0
    # flat inventory → reservation price == mid
    assert reservation_price(100.0, 0.0, 0.1, 2.0, 1.0) == 100.0
    # spread positive and symmetric around reservation price
    spread = optimal_spread(gamma=0.1, sigma=2.0, time_to_horizon=1.0, k=1.5)
    assert spread > 0
    bid, ask = quote_prices(100.0, 0.0, 0.1, 2.0, 1.0, 1.5)
    assert bid < ask
    assert (ask - bid) == pytest.approx(spread)


def test_hb_mm_rejects_bad_params():
    from vendor.hb_mm import optimal_spread

    with pytest.raises(ValueError):
        optimal_spread(gamma=0.0, sigma=1.0, time_to_horizon=1.0, k=1.0)


def test_vt_factors_reference_values():
    from vendor.vt_factors import alpha_momentum, cross_sectional_zscore

    z = cross_sectional_zscore([1.0, 2.0, 3.0])
    assert z.mean() == pytest.approx(0.0)
    assert np.allclose(z, [-1.224744871, 0.0, 1.224744871])
    # 10% up over 1 bar
    assert alpha_momentum([100.0, 110.0], lookback=1) == pytest.approx(0.10)


def test_vt_validation_stats_deterministic():
    from vendor.vt_validation import bootstrap_sharpe_ci, permutation_pvalue

    rng = np.random.default_rng(1)
    rets = list(rng.normal(0.01, 0.02, 200))  # positive-drift series
    p1 = permutation_pvalue(rets, n=500, seed=7)
    p2 = permutation_pvalue(rets, n=500, seed=7)
    assert p1 == p2  # deterministic for a fixed seed
    assert 0.0 <= p1 <= 1.0
    lo, hi = bootstrap_sharpe_ci(rets, n=500, seed=7)
    assert lo <= hi


def test_jesse_engine_metrics():
    from vendor.jesse_engine import max_drawdown, total_return

    assert total_return([100.0, 110.0]) == pytest.approx(0.10)
    assert max_drawdown([100.0, 120.0, 90.0, 130.0]) == pytest.approx((90.0 - 120.0) / 120.0)


def test_ft_protections_stoploss_guard():
    from datetime import datetime, timedelta, timezone

    from vendor.ft_protections import StoplossGuard

    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    guard = StoplossGuard(trigger_count=4, lookback_hours=2, lock_hours=1)
    times = [now - timedelta(minutes=10 * i) for i in range(4)]  # 4 within 2h
    lock = guard.evaluate(times, now)
    assert lock is not None and lock.scope == "global"
    # only 3 → no lock
    assert guard.evaluate(times[:3], now) is None


def test_vt_research_import_forbidden_contract_present():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    contracts = data["tool"]["importlinter"]["contracts"]
    names = [c["name"] for c in contracts]
    assert any("vt_research" in n for n in names)
    vt = next(c for c in contracts if "vt_research" in c["name"])
    assert "vendor.vt_research" in vt["forbidden_modules"]
    assert "aimos" in vt["source_modules"]
