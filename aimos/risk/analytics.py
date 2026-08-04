"""VaR/ES + factor decomposition + alpha/beta attribution (§24.3-24.4, card P5-T7).

VaR/ES via historical simulation (fat crypto tails — no parametric assumption).
Factor split into BTC-beta vs idiosyncratic. Alpha/beta attribution by regressing
strategy returns on a benchmark. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class VaRResult:
    var_pct: float  # 1-day VaR at the given confidence (positive = loss)
    es_pct: float  # Expected Shortfall (mean loss beyond VaR)


def historical_var_es(portfolio_returns: Sequence[float], confidence: float = 0.95) -> VaRResult:
    """Historical-simulation VaR + ES (§24.3). Returns positive loss magnitudes."""
    r = np.asarray(portfolio_returns, dtype=float)
    if r.size == 0:
        return VaRResult(0.0, 0.0)
    q = np.quantile(r, 1.0 - confidence)  # lower-tail return (negative)
    var_pct = -float(q) * 100.0 + 0.0
    tail = r[r <= q]
    es_pct = -float(tail.mean()) * 100.0 + 0.0 if tail.size else var_pct
    return VaRResult(var_pct, es_pct)


@dataclass
class Attribution:
    alpha_annualized: float
    beta: float
    t_stat: float


def alpha_beta(
    strategy_returns: Sequence[float], benchmark_returns: Sequence[float], periods_per_year: float = 365.0
) -> Attribution:
    """OLS regression of strategy on benchmark → alpha (annualized), beta, t-stat (§24.4)."""
    y = np.asarray(strategy_returns, dtype=float)
    x = np.asarray(benchmark_returns, dtype=float)
    n = y.size
    if n < 3 or x.std() == 0:
        return Attribution(0.0, 0.0, 0.0)
    beta, alpha = np.polyfit(x, y, 1)
    resid = y - (beta * x + alpha)
    dof = n - 2
    s_err = np.sqrt((resid ** 2).sum() / dof)
    x_var = ((x - x.mean()) ** 2).sum()
    se_alpha = s_err * np.sqrt(1.0 / n + x.mean() ** 2 / x_var) if x_var > 0 else 0.0
    t_stat = float(alpha / se_alpha) if se_alpha > 0 else 0.0
    return Attribution(float(alpha) * periods_per_year, float(beta), t_stat)


def factor_decomposition(portfolio_var: float, btc_beta_var: float) -> dict[str, float]:
    """Split portfolio variance into BTC-beta vs idiosyncratic (§24.3)."""
    if portfolio_var <= 0:
        return {"btc_beta_pct": 0.0, "idiosyncratic_pct": 0.0}
    beta_pct = min(btc_beta_var / portfolio_var, 1.0) * 100.0
    return {"btc_beta_pct": beta_pct, "idiosyncratic_pct": 100.0 - beta_pct}


__all__ = ["Attribution", "VaRResult", "alpha_beta", "factor_decomposition", "historical_var_es"]
