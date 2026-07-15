"""Pure technical-indicator math (§5.2-5.4, §5.12).

Deterministic numpy/pandas implementations of the indicators the observation
engines need (RSI, MACD, ROC, EMA, ATR, rolling z-score, beta). Kept in ``core``
so the periods are ordinary function arguments and the math constants (100 for
RSI, etc.) live outside the magic-number-linted decision-path layers (§23.12).

SPEC-GAP (§5.3): the plan suggests the ``ta`` library; we implement in
numpy/pandas instead — no extra runtime dependency, fully deterministic and
testable, identical formulas. This is the simplest compliant option.

All functions operate on data ``<= t`` only (no lookahead); callers pass windows
that already end at the decision time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_RSI_SCALE = 100.0


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder-style RSI on ``close`` (§5.3 rule 1)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = _RSI_SCALE - (_RSI_SCALE / (1.0 + rs))
    out = out.where(avg_loss != 0.0, _RSI_SCALE)  # all-gain window → 100
    return out


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """MACD line, signal, histogram (§5.3 rule 2)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def roc(close: pd.Series, period: int) -> pd.Series:
    """Rate of change over ``period`` bars (§5.3 rule 3)."""
    return close.pct_change(periods=period)


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range from o/h/l/c (§5.4)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average true range (Wilder smoothing) (§5.4 rule 1)."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """z-score of the latest value vs its trailing ``window`` (ddof=0)."""
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def zscore_last(values: np.ndarray) -> float:
    """z-score of the last element vs the whole array (ddof=0). 0 if flat."""
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        return 0.0
    std = arr.std()
    if std == 0:
        return 0.0
    return float((arr[-1] - arr.mean()) / std)


def beta(asset_returns: np.ndarray, market_returns: np.ndarray) -> float:
    """OLS beta of asset vs market returns (§5.12 rule 1)."""
    a = np.asarray(asset_returns, dtype=float)
    m = np.asarray(market_returns, dtype=float)
    if a.size < 2 or m.size < 2 or a.size != m.size:
        return 0.0
    var = m.var()
    if var == 0:
        return 0.0
    return float(np.cov(a, m, ddof=0)[0, 1] / var)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation; 0 when undefined."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or a.size != b.size or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


__all__ = [
    "atr",
    "beta",
    "correlation",
    "ema",
    "macd",
    "roc",
    "rolling_zscore",
    "rsi",
    "sma",
    "true_range",
    "zscore_last",
]
