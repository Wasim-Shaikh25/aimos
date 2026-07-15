"""Price Action engine (§5.1, card P2-T2).

Swings (confirmed k bars late — no lookahead), structure trend, BOS, CHoCH,
FVG tracking, range detection, and key_levels. Emits per analysis timeframe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from aimos.core.indicators import atr
from aimos.core.normalize import HALF
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


def find_swings(df: pd.DataFrame, k: int) -> tuple[list[int], list[int]]:
    """Swing-high / swing-low indices, confirmed only k bars later (§5.1 rule 1)."""
    highs: list[int] = []
    lows: list[int] = []
    h = df["high"].values
    low = df["low"].values
    n = len(df)
    for i in range(k, n - k):  # i+k must exist → last k bars never confirmed
        if h[i] == h[i - k : i + k + 1].max():
            highs.append(i)
        if low[i] == low[i - k : i + k + 1].min():
            lows.append(i)
    return highs, lows


class PriceActionEngine(ObservationEngine):
    name = "price_action_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        out: list[Evidence] = []
        for tf, df in ctx.candles.items():
            if df is None or len(df) < self._min_bars():
                continue
            out.extend(self._observe_tf(ctx, tf, df))
        return out

    # -- config shortcuts ----------------------------------------------------

    def _pa(self) -> dict:
        return self.cfg["price_action"]

    def _atr_period(self) -> int:
        return int(self.cfg["volatility"]["atr_period"])

    def _min_bars(self) -> int:
        pa = self._pa()
        return max(int(pa["range_lookback"]), self._atr_period()) + int(pa["swing_k"])

    # -- per-timeframe logic -------------------------------------------------

    def _observe_tf(self, ctx: MarketContext, tf: Timeframe, df: pd.DataFrame) -> list[Evidence]:
        pa = self._pa()
        k = int(pa["swing_k"])
        out: list[Evidence] = []
        atr_series = atr(df, self._atr_period())
        atr_now = float(atr_series.iloc[-1])
        if not np.isfinite(atr_now) or atr_now <= 0:
            return out
        close = float(df["close"].iloc[-1])
        ts = df.index[-1].to_pydatetime()
        highs, lows = find_swings(df, k)

        structure = self._structure(ctx, tf, ts, df, highs, lows)
        # key_levels ride in the structure evidence's meta — Layer 2 copies them
        # into MarketUnderstanding.key_levels (§5.1). Attach when we have one.
        if structure:
            structure[0].meta["key_levels"] = self._key_levels(df, highs, lows)
        out.extend(structure)
        bos = self._bos(ctx, tf, ts, df, highs, lows, atr_now, close)
        out.extend(bos)
        out.extend(self._choch(ctx, tf, ts, df, highs, lows, bos, structure))
        out.extend(self._fvg(ctx, tf, ts, df, atr_now, close))
        out.extend(self._range(ctx, tf, ts, df, atr_series))
        return out

    def _ev(self, ctx, tf, ts, name, value, direction, strength, meta=None) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}",
            symbol=ctx.symbol,
            timeframe=tf,
            timestamp=ts,
            name=name,
            value=float(value),
            direction=direction,
            strength=self._clamp01(float(strength)),
            reliability=self.reliability,
            meta=meta or {},
        )

    def _structure(self, ctx, tf, ts, df, highs, lows) -> list[Evidence]:
        if len(highs) < 2 or len(lows) < 2:
            return []
        h = df["high"].values
        low = df["low"].values
        hh = h[highs[-1]] > h[highs[-2]]
        hl = low[lows[-1]] > low[lows[-2]]
        conforming_up = int(hh) + int(hl)
        conforming_down = int(not hh) + int(not hl)
        total = 2
        if conforming_up == total:
            direction, strength = Direction.BULLISH, conforming_up / total
        elif conforming_down == total:
            direction, strength = Direction.BEARISH, conforming_down / total
        else:
            direction, strength = Direction.NEUTRAL, HALF
        return [self._ev(ctx, tf, ts, "structure_trend", strength, direction, strength)]

    def _bos(self, ctx, tf, ts, df, highs, lows, atr_now, close) -> list[Evidence]:
        pa = self._pa()
        recency = int(pa["bos_recency_bars"])
        n = len(df)
        h = df["high"].values
        low = df["low"].values
        out: list[Evidence] = []
        # bullish BOS: recent close beyond most recent confirmed swing high
        if highs:
            level = h[highs[-1]]
            crossed = df["close"].values[-recency:] > level
            if close > level and crossed.any():
                out.append(self._ev(ctx, tf, ts, "bos", (close - level) / atr_now,
                                     Direction.BULLISH, self._z_strength((close - level) / atr_now),
                                     {"level": float(level)}))
                return out
        if lows:
            level = low[lows[-1]]
            crossed = df["close"].values[-recency:] < level
            if close < level and crossed.any():
                out.append(self._ev(ctx, tf, ts, "bos", (level - close) / atr_now,
                                     Direction.BEARISH, self._z_strength((level - close) / atr_now),
                                     {"level": float(level)}))
        return out

    def _choch(self, ctx, tf, ts, df, highs, lows, bos, structure) -> list[Evidence]:
        if not bos or not structure:
            return []
        struct_dir = structure[0].direction
        bos_dir = bos[0].direction
        # CHoCH = BOS opposite to current structure trend
        if struct_dir in (Direction.BULLISH, Direction.BEARISH) and bos_dir != struct_dir:
            return [self._ev(ctx, tf, ts, "choch", bos[0].value, bos_dir, bos[0].strength)]
        return []

    def _fvg(self, ctx, tf, ts, df, atr_now, close) -> list[Evidence]:
        pa = self._pa()
        prox = float(pa["fvg_proximity_atr"]) * atr_now
        h = df["high"].values
        low = df["low"].values
        n = len(df)
        # scan for the nearest unfilled gap; emit fvg_nearby if price within prox
        best: tuple[float, Direction, float] | None = None
        for i in range(2, n):
            if low[i] > h[i - 2]:  # bullish FVG between h[i-2] and low[i]
                edge = low[i]
                if not (df["low"].values[i:] < h[i - 2]).any():  # unfilled
                    dist = abs(close - edge)
                    if dist <= prox and (best is None or dist < best[0]):
                        best = (dist, Direction.BULLISH, edge)
            if h[i] < low[i - 2]:  # bearish FVG
                edge = h[i]
                if not (df["high"].values[i:] > low[i - 2]).any():
                    dist = abs(close - edge)
                    if dist <= prox and (best is None or dist < best[0]):
                        best = (dist, Direction.BEARISH, edge)
        if best is None:
            return []
        dist, direction, edge = best
        strength = 1 - dist / prox if prox > 0 else 0
        return [self._ev(ctx, tf, ts, "fvg_nearby", edge, direction, strength, {"edge": float(edge)})]

    def _range(self, ctx, tf, ts, df, atr_series) -> list[Evidence]:
        pa = self._pa()
        lookback = int(pa["range_lookback"])
        mult = float(pa["range_atr_mult"])
        window = df.iloc[-lookback:]
        atr_lb = float(atr_series.iloc[-1])
        if atr_lb <= 0:
            return []
        width = float(window["high"].max() - window["low"].min())
        if width < mult * atr_lb:
            strength = 1 - width / (mult * atr_lb)
            return [self._ev(ctx, tf, ts, "range_bound", width, Direction.NEUTRAL, strength)]
        return []

    def _key_levels(self, df, highs, lows) -> dict:
        count = int(self._pa()["key_levels_count"])
        h = df["high"].values
        low = df["low"].values
        return {
            "swing_highs": [float(h[i]) for i in highs[-count:]],
            "swing_lows": [float(low[i]) for i in lows[-count:]],
        }


__all__ = ["PriceActionEngine", "find_swings"]
