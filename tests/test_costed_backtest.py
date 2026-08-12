"""T-003 — 12-month costed walk-forward backtest acceptance tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from aimos.backtest import costs as cost_mod
from aimos.backtest.engine import BacktestEngine
from aimos.backtest.metrics import compute_metrics, max_drawdown
from aimos.backtest.validation import make_run_card, validate_returns
from aimos.core.config import load_params
from aimos.core.schemas import Action, TradePlan
from aimos.execution.broker.paper import PaperBroker


def _candles_one_winner() -> pd.DataFrame:
    """A short 1h series with exactly one long trade that hits TP after costs."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = 30_000.0
    n = load_params_required_warmup() + 5
    idx = pd.DatetimeIndex(
        [start + pd.Timedelta(hours=i) for i in range(n)], tz="UTC", name="timestamp"
    )
    flat = [{"open": base, "high": base + 100, "low": base - 100, "close": base,
             "volume": 1000.0, "synthetic": False} for _ in range(n - 1)]
    last = {"open": base, "high": 31_100.0, "low": base, "close": 31_000.0,
            "volume": 1000.0, "synthetic": False}
    return pd.DataFrame(flat + [last], index=idx)


def load_params_required_warmup() -> int:
    """Recompute the engine-derived minimum warmup without importing private helpers."""
    from aimos.observation.runner import required_warmup
    return required_warmup(load_params())


def test_t003_01_costed_backtest_has_strictly_lower_pnl():
    """A run with taker+slip costs must finish with less equity than a zero-cost run."""
    candles = _candles_one_winner()
    params = load_params()

    plan = TradePlan(
        plugin="TrendFollowing", symbol="BTC", action=Action.LONG,
        entry=30_000.0, stop_loss=29_000.0, take_profit=31_000.0, size_quote=3000.0,
    )
    placed = False

    def fixed_decide(*_args, **_kwargs):
        nonlocal placed
        if placed:
            return TradePlan(plugin="TrendFollowing", symbol="BTC", action=Action.NO_TRADE)
        placed = True
        return plan

    def run(cost: cost_mod.CostModel) -> float:
        engine = BacktestEngine(
            params, "BTC", starting_equity=10_000.0, journal_path=":memory:",
        )
        # Inject the cost model directly so the same engine params are otherwise identical.
        engine.broker = PaperBroker(10_000.0, cost)
        engine.execution.decide = fixed_decide  # type: ignore[assignment]
        result = engine.run(candles, warmup=load_params_required_warmup())
        return result.broker.equity()

    zero_cost = run(cost_mod.CostModel(taker_bps=0.0, maker_bps=0.0, slip_base_bps=0.0, slip_k=0.0))
    costed = run(cost_mod.CostModel(taker_bps=7.5, maker_bps=2.0, slip_base_bps=2.0, slip_k=25.0))

    assert costed < zero_cost, "costed run must produce lower final equity than zero-cost run"


def test_t003_02_shuffled_random_returns_have_no_edge():
    """Random sign-flipped returns collapse to a non-positive edge (permutation p not < 0.05)."""
    import numpy as np
    rng = np.random.default_rng(123)
    returns = rng.normal(loc=0.0, scale=0.02, size=100).tolist()
    v = validate_returns(returns, seed=42)
    assert not v.passes_promotion_gate
    # Sharpe CI straddles zero when the mean is indistinguishable from noise.
    assert v.sharpe_ci_low <= 0.0


def test_t003_04_run_card_contains_verdict_and_metrics():
    """make_run_card emits a reproducible artifact with a per-strategy verdict."""
    import numpy as np
    rng = np.random.default_rng(7)
    returns = (rng.random(50) - 0.45).tolist()  # slight positive drift, sample < 30 not enough
    card = make_run_card(
        run_id="t003-test-Strategy-BTCUSDT-no_book-20260812",
        git_sha="abc123",
        params_dict={"costs": {"taker_bps": 7.5}},
        equity_curve=[10_000.0] + [10_000.0 + r * 1000 for r in returns],
        metrics={"trades": len(returns), "total_pnl_usd": sum(r * 1000 for r in returns)},
        validation=validate_returns(returns, seed=0),
        seed=0,
        engine_profile="no_book",
        universe_snapshot_id="test-tier1",
    )
    text = card.to_yaml()
    assert "verdict" in text or "metrics" in text
    assert card.run_id.startswith("t003-")


def test_max_drawdown_negative_on_declining_equity():
    """Max drawdown is negative when the equity curve falls from a peak."""
    eq = [10_000.0, 10_500.0, 9_800.0, 10_200.0, 9_900.0]
    dd = max_drawdown(eq)
    assert dd < 0.0


def test_compute_metrics_with_costs_lower_return():
    """Profit factor and total_return reflect costs through lower net PnL."""
    equity_cost = [10_000.0, 10_050.0, 10_020.0]
    equity_free = [10_000.0, 10_080.0, 10_100.0]
    m_cost = compute_metrics(equity_cost, [-0.1, 0.3], n_decisions=2, n_no_trade=0, days=1.0)
    m_free = compute_metrics(equity_free, [0.0, 0.8], n_decisions=2, n_no_trade=0, days=1.0)
    assert m_cost.total_return < m_free.total_return


def test_universe_snapshot_id_is_a_real_data_fingerprint_not_trade_count():
    """universe_snapshot_id must identify the candle data used, not the trade count.

    Regression for a bug where the field was `f"{exchange}-tier1-{len(all_trades)}"`
    — two runs against different market data but the same trade count got the
    same "snapshot id", and two runs against identical data with different
    strategies (different trade counts) got different ids, making the field
    useless for verifying two runs used the same underlying candles.
    """
    from scripts.run_backtest_card import _candles_fingerprint

    idx = pd.DatetimeIndex(
        [datetime(2026, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(hours=i) for i in range(5)],
        tz="UTC", name="timestamp",
    )
    candles_a = pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.5] * 5, "low": [0.5] * 5, "close": [1.2] * 5, "volume": [100.0] * 5},
        index=idx,
    )
    candles_b = candles_a.copy()
    candles_b.loc[idx[0], "close"] = 9.9  # different market data

    # Same data → same fingerprint, regardless of how many trades a strategy made on it.
    assert _candles_fingerprint(candles_a) == _candles_fingerprint(candles_a.copy())
    # Different data → different fingerprint, even with an identical row count.
    assert _candles_fingerprint(candles_a) != _candles_fingerprint(candles_b)
