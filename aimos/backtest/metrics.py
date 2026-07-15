"""Backtest metrics (§9.3, card P4-T8).

Total return, CAGR, Sharpe, Sortino, max drawdown, hit rate, avg R, profit
factor, exposure, turnover, NO_TRADE rate. Deterministic given the same journal
so identical-hash runs produce identical metrics (extends §13 test 7). Not in the
linted layers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

_TRADING_DAYS = 365.0  # crypto trades every day


@dataclass
class Metrics:
    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    hit_rate: float = 0.0
    avg_r: float = 0.0
    profit_factor: float = 0.0
    exposure_pct: float = 0.0
    no_trade_rate: float = 0.0
    n_decisions: int = 0
    n_trades: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _sharpe(daily_returns: np.ndarray) -> float:
    if daily_returns.size < 2:
        return 0.0
    std = daily_returns.std(ddof=1)
    if std == 0:
        return 0.0
    return float(daily_returns.mean() / std * math.sqrt(_TRADING_DAYS))


def _sortino(daily_returns: np.ndarray) -> float:
    if daily_returns.size < 2:
        return 0.0
    downside = daily_returns[daily_returns < 0]
    dd = downside.std(ddof=1) if downside.size > 1 else 0.0
    if dd == 0:
        return 0.0
    return float(daily_returns.mean() / dd * math.sqrt(_TRADING_DAYS))


def max_drawdown(equity_curve: np.ndarray) -> float:
    if equity_curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak
    return float(dd.min())


def compute_metrics(
    equity_curve: list[float],
    trade_r_multiples: list[float],
    n_decisions: int,
    n_no_trade: int,
    n_bars_in_position: int = 0,
    days: float = 1.0,
) -> Metrics:
    eq = np.asarray(equity_curve, dtype=float)
    m = Metrics(n_decisions=n_decisions, n_trades=len(trade_r_multiples))
    if eq.size >= 2 and eq[0] > 0:
        m.total_return = float(eq[-1] / eq[0] - 1.0)
        rets = np.diff(eq) / eq[:-1]
        m.sharpe = _sharpe(rets)
        m.sortino = _sortino(rets)
        m.max_drawdown = max_drawdown(eq)
        if days > 0:
            m.cagr = float((eq[-1] / eq[0]) ** (_TRADING_DAYS / days) - 1.0)
    if trade_r_multiples:
        r = np.asarray(trade_r_multiples, dtype=float)
        m.avg_r = float(r.mean())
        wins = r[r > 0]
        losses = r[r < 0]
        m.hit_rate = float(wins.size / r.size)
        gross_win = float(wins.sum())
        gross_loss = float(-losses.sum())
        m.profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
    if n_decisions > 0:
        m.no_trade_rate = n_no_trade / n_decisions
        m.exposure_pct = n_bars_in_position / n_decisions
    return m


__all__ = ["Metrics", "compute_metrics", "max_drawdown"]
