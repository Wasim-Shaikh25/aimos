"""Shared test fixtures/helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from aimos.core.config import load_params
from aimos.core.clock import LiveClock


def obs_cfg() -> dict:
    """The observation config subtree as a plain dict (engine cfg)."""
    return load_params().observation.model_dump()


def reliability(engine_key: str) -> float:
    rel = load_params().weights.model_dump().get("reliability", {})
    return float(rel.get(engine_key, 0.5))


def make_mu(**over):
    """A §25.9-style bullish TRENDING_UP MarketUnderstanding for execution tests."""
    from aimos.core.schemas import Behavior, Direction, MarketUnderstanding, Regime

    base = dict(
        symbol="SOL", timestamp=datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc),
        regime=Regime.TRENDING_UP, regime_probs={"trending_up": 0.7, "ranging": 0.3},
        behavior=Behavior.CONTINUATION, behavior_probs={"continuation": 0.7},
        direction_bias=Direction.BULLISH, p_up=0.766, horizon_minutes=240,
        confidence=0.428, coin_health=74, opportunity_score=71, risk_score=38,
        key_levels={"price": 150.0, "atr": 2.1, "swing_lows": [146.8], "swing_highs": [153.2]},
    )
    base.update(over)
    return MarketUnderstanding(**base)


def make_caps(**over):
    from aimos.core.schemas import CapacityCaps

    base = dict(max_equity_pct_per_asset=25, max_pct_of_24h_volume=0.1,
                max_pct_of_book_depth=15, max_exit_slippage_bps=30, stress_exit_bps=100)
    base.update(over)
    return CapacityCaps(**base)


def make_exec_ctx(equity=10_000.0, **over):
    from aimos.core.schemas import ExecContext

    base = dict(
        equity_usdt=equity, open_positions=[], portfolio_heat_pct=0.0,
        fee_taker_bps=7.5, fee_maker_bps=2.0, slippage_entry_bps=2.0, slippage_exit_bps=2.0,
        venue="binance", caps=make_caps(),
    )
    base.update(over)
    return ExecContext(**base)


def make_candles(
    closes,
    start: datetime | None = None,
    tf_minutes: int = 60,
    highs=None,
    lows=None,
    opens=None,
    volumes=None,
    synthetic=None,
) -> pd.DataFrame:
    """Build an OHLCV(+synthetic) DataFrame from a close series for engine tests."""
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = len(closes)
    idx = pd.DatetimeIndex(
        [start + timedelta(minutes=tf_minutes * i) for i in range(n)], tz="UTC", name="timestamp"
    )
    opens = opens if opens is not None else [closes[max(i - 1, 0)] for i in range(n)]
    highs = highs if highs is not None else [max(opens[i], closes[i]) + 1 for i in range(n)]
    lows = lows if lows is not None else [min(opens[i], closes[i]) - 1 for i in range(n)]
    volumes = volumes if volumes is not None else [100.0] * n
    synthetic = synthetic if synthetic is not None else [False] * n
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": volumes, "synthetic": synthetic},
        index=idx,
    )


class FakeClock:
    """Manually-advanced UTC clock for deterministic time-based tests (§4.5)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)

    def set(self, t: datetime) -> None:
        self._t = t
