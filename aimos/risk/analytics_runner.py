"""Risk-analytics runner — wires VaR/ES + alpha/beta + factor split to runtime data.

Computes a daily risk report from the live equity curve and benchmark returns
(BTC + equal-weight T1 basket).  The math lives in ``aimos.risk.analytics``;
this module fetches the benchmark series and aligns them with strategy returns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from aimos.risk.analytics import alpha_beta, factor_decomposition, historical_var_es

DataSource = Callable[[str, str, int], pd.DataFrame]


def _returns_from_equity(equity: Sequence[float]) -> np.ndarray:
    """Per-tick strategy returns from the equity curve."""
    arr = np.asarray(equity, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return np.diff(arr) / arr[:-1]


def _benchmark_returns(
    data_source: DataSource,
    symbols: Sequence[str],
    timeframe: str,
    bars: int,
) -> dict[str, np.ndarray]:
    """Fetch close prices and return per-symbol return arrays."""
    out: dict[str, np.ndarray] = {}
    for sym in symbols:
        try:
            df = data_source(sym, timeframe, bars)
        except Exception:
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes = df["close"].to_numpy(dtype=float)
        if len(closes) < 2:
            continue
        out[sym] = np.diff(closes) / closes[:-1]
    return out


def _equal_weight_returns(symbol_returns: Mapping[str, np.ndarray]) -> np.ndarray:
    """Mean return across symbols, aligning at the most recent end."""
    if not symbol_returns:
        return np.array([])
    min_len = min(len(r) for r in symbol_returns.values())
    if min_len < 1:
        return np.array([])
    stacked = np.vstack([r[-min_len:] for r in symbol_returns.values()])
    return stacked.mean(axis=0)


def _risk_cfg(params: Any) -> dict[str, Any]:
    """Extract the ``risk`` config dict, falling back to empty defaults."""
    if params is None:
        return {}
    if isinstance(params, dict):
        return dict(params.get("risk") or {})
    cfg = getattr(params, "risk", None)
    if cfg is None:
        return {}
    if hasattr(cfg, "model_dump"):
        return dict(cfg.model_dump())
    return dict(cfg)


def _paper_timeframe(params: Any) -> str:
    """Timeframe for benchmark series — config override, else paper loop."""
    cfg = _risk_cfg(params)
    tf = cfg.get("timeframe")
    if tf:
        return str(tf)
    if params is None:
        return "1h"
    paper: Any = getattr(params, "paper", None)
    if paper is None:
        return "1h"
    if hasattr(paper, "model_dump"):
        paper = paper.model_dump()
    if isinstance(paper, dict):
        return str(paper.get("timeframe", "1h"))
    return "1h"


def _t1_symbols(universe: Any, params: Any) -> list[str]:
    """Equal-weight T1 basket symbols from the universe tier map."""
    if universe is None:
        return []
    tiers = getattr(universe, "tiers", None)
    if not tiers:
        return []
    if isinstance(tiers, dict):
        return [f"{b}/USDT" for b, t in tiers.items() if str(t).lower() == "t1"]
    return []


def compute_risk_report(
    equity: Sequence[float],
    params: Any,
    data_source: DataSource,
    universe: Any = None,
    clock: Any = None,
) -> dict[str, Any]:
    """Build a JSON-ready risk report from the running equity curve.

    Parameters
    ----------
    equity: sequence of equity values (one per tick/decision).
    params: ``Params`` tree (or dict) with ``risk.*`` and ``paper.timeframe``.
    data_source: ``fetch(symbol, timeframe, bars) -> DataFrame`` callable.
    universe: runtime ``Universe`` (for T1 basket membership).
    clock: optional clock with ``.now()`` for ``computed_at`` timestamp.
    """
    cfg = _risk_cfg(params)
    if not bool(cfg.get("enabled", True)):
        return {"note": "risk analytics disabled"}

    strategy_returns = _returns_from_equity(equity)
    n = len(strategy_returns)
    min_samples = int(cfg.get("min_samples", 30))
    if n < min_samples:
        return {"note": f"insufficient equity history ({n} < {min_samples})"}

    timeframe = _paper_timeframe(params)
    bars = n + 1

    # BTC benchmark
    btc_returns: np.ndarray = np.array([])
    try:
        btc_df = data_source("BTC/USDT", timeframe, bars)
        if btc_df is not None and not btc_df.empty and "close" in btc_df.columns:
            closes = btc_df["close"].to_numpy(dtype=float)
            if len(closes) >= 2:
                btc_returns = np.diff(closes) / closes[:-1]
    except Exception:
        pass

    # Equal-weight T1 basket
    basket_symbols = _t1_symbols(universe, params)
    if not basket_symbols and params is not None:
        dev = getattr(params, "dev_symbols", None) or []
        basket_symbols = [s for s in dev if "BTC" not in s.upper()]
    basket_raw = _benchmark_returns(data_source, basket_symbols, timeframe, bars)
    basket_returns = _equal_weight_returns(basket_raw)

    # Align all series to the most recent overlapping window.
    arrays = [strategy_returns]
    if len(btc_returns) > 0:
        arrays.append(btc_returns)
    if len(basket_returns) > 0:
        arrays.append(basket_returns)
    min_len = min(len(a) for a in arrays)
    if min_len < 3:
        return {"note": f"insufficient aligned benchmark samples ({min_len})"}

    trim_strategy = strategy_returns[-min_len:]
    trim_btc = btc_returns[-min_len:] if len(btc_returns) > 0 else np.zeros(min_len)
    trim_basket = basket_returns[-min_len:] if len(basket_returns) > 0 else np.zeros(min_len)

    var95 = historical_var_es(trim_strategy, 0.95)
    var99 = historical_var_es(trim_strategy, 0.99)

    btc_attr = alpha_beta(trim_strategy, trim_btc, 365.0)
    basket_attr = alpha_beta(trim_strategy, trim_basket, 365.0)

    port_var = float(np.var(trim_strategy))
    btc_beta_var = float((btc_attr.beta ** 2) * np.var(trim_btc))
    factor = factor_decomposition(port_var, btc_beta_var)

    if clock is not None and hasattr(clock, "now"):
        computed_at = clock.now().isoformat()
    else:
        computed_at = datetime.now(timezone.utc).isoformat()

    return {
        "var_95_pct": round(float(var95.var_pct), 4),
        "es_95_pct": round(float(var95.es_pct), 4),
        "var_99_pct": round(float(var99.var_pct), 4),
        "es_99_pct": round(float(var99.es_pct), 4),
        "btc": {
            "alpha_annualized": round(float(btc_attr.alpha_annualized), 6),
            "beta": round(float(btc_attr.beta), 4),
            "t_stat": round(float(btc_attr.t_stat), 4),
        },
        "basket": {
            "alpha_annualized": round(float(basket_attr.alpha_annualized), 6),
            "beta": round(float(basket_attr.beta), 4),
            "t_stat": round(float(basket_attr.t_stat), 4),
        },
        "factor": {
            "btc_beta_pct": round(float(factor["btc_beta_pct"]), 2),
            "idiosyncratic_pct": round(float(factor["idiosyncratic_pct"]), 2),
        },
        "sample_size": min_len,
        "computed_at": computed_at,
    }


__all__ = ["compute_risk_report", "DataSource"]
