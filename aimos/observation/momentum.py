"""Momentum engine (§5.3, card P2-T3)."""

from __future__ import annotations

import numpy as np

from aimos.core.indicators import atr, ema, macd, roc, rsi
from aimos.core.schemas import Direction, Evidence, MarketContext
from aimos.observation.base import ObservationEngine, real_candles


class MomentumEngine(ObservationEngine):
    name = "momentum_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        out: list[Evidence] = []
        for tf, raw in ctx.candles.items():
            if raw is None:
                continue
            df = real_candles(raw)
            if len(df) < self._min_bars():
                continue
            out.extend(self._observe_tf(ctx, tf, df))
        return out

    def _m(self) -> dict:
        return self.cfg["momentum"]

    def _min_bars(self) -> int:
        m = self._m()
        return max(int(m["macd_hist_std_window"]), int(m["roc_hist_window"]), int(m["ema_period"])) + 1

    def _ev(self, ctx, tf, ts, name, value, direction, strength, meta=None) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=tf, timestamp=ts,
            name=name, value=float(value), direction=direction,
            strength=self._clamp01(float(strength)), reliability=self.reliability, meta=meta or {},
        )

    def _observe_tf(self, ctx, tf, df) -> list[Evidence]:
        m = self._m()
        close = df["close"]
        ts = df.index[-1].to_pydatetime()
        out: list[Evidence] = []

        # rule 1: RSI
        rsi_v = float(rsi(close, int(m["rsi_period"])).iloc[-1])
        if np.isfinite(rsi_v):
            div = float(m["rsi_strength_div"])
            if rsi_v > float(m["rsi_overbought"]):
                out.append(self._ev(ctx, tf, ts, "rsi_overbought", rsi_v, Direction.BEARISH,
                                     (rsi_v - float(m["rsi_overbought"])) / div))
            elif rsi_v < float(m["rsi_oversold"]):
                out.append(self._ev(ctx, tf, ts, "rsi_oversold", rsi_v, Direction.BULLISH,
                                     (float(m["rsi_oversold"]) - rsi_v) / div))
            # RSI in [band_low, band_high] → emit nothing

        # rule 2: MACD histogram sign flip
        macd_df = macd(close, int(m["macd_fast"]), int(m["macd_slow"]), int(m["macd_signal"]))
        hist = macd_df["hist"]
        if len(hist.dropna()) > 1:
            cur, prev = float(hist.iloc[-1]), float(hist.iloc[-2])
            if np.sign(cur) != np.sign(prev) and cur != 0:
                std = float(hist.rolling(int(m["macd_hist_std_window"])).std().iloc[-1])
                z = cur / std if std and np.isfinite(std) else 0.0
                out.append(self._ev(ctx, tf, ts, "macd_cross", cur,
                                     Direction.BULLISH if cur > 0 else Direction.BEARISH,
                                     self._z_strength(z)))

        # rule 3: ROC z-scored
        roc_series = roc(close, int(m["roc_period"]))
        roc_z = self._zscore(roc_series, int(m["roc_hist_window"]))
        if roc_z is not None and roc_z != 0:
            out.append(self._ev(ctx, tf, ts, "momentum", roc_series.iloc[-1],
                                 Direction.BULLISH if roc_z > 0 else Direction.BEARISH,
                                 self._z_strength(roc_z)))

        # rule 4: EMA(50) slope / ATR
        ema_slope = self._ema_slope(df, m)
        if ema_slope is not None and ema_slope != 0:
            out.append(self._ev(ctx, tf, ts, "ema_slope", ema_slope,
                                 Direction.BULLISH if ema_slope > 0 else Direction.BEARISH,
                                 self._z_strength(ema_slope)))

        # rule 5: momentum decay
        decay = self._decay(ctx, tf, ts, df, roc_series, m)
        if decay is not None:
            out.append(decay)
        return out

    def _zscore(self, series, window):
        s = series.dropna()
        if len(s) < window:
            return None
        tail = s.iloc[-window:]
        std = float(tail.std(ddof=0))
        if std == 0:
            return 0.0
        return float((s.iloc[-1] - tail.mean()) / std)

    def _ema_slope(self, df, m):
        e = ema(df["close"], int(m["ema_period"]))
        bars = int(m["ema_slope_bars"])
        if len(e.dropna()) <= bars:
            return None
        slope = float(e.iloc[-1] - e.iloc[-1 - bars])
        atr_now = float(atr(df, int(self.cfg["volatility"]["atr_period"])).iloc[-1])
        if not np.isfinite(atr_now) or atr_now <= 0:
            return None
        return slope / atr_now

    def _decay(self, ctx, tf, ts, df, roc_series, m):
        n = int(m["momentum_decay_bars"])
        mag = roc_series.abs().dropna()
        if len(mag) < n + 1:
            return None
        recent = mag.iloc[-(n + 1):].values
        declining = all(recent[i] < recent[i - 1] for i in range(1, len(recent)))
        if not declining:
            return None
        # price still trending: sign of net move over the decay window
        trend = float(df["close"].iloc[-1] - df["close"].iloc[-1 - n])
        if trend == 0:
            return None
        direction = Direction.BEARISH if trend > 0 else Direction.BULLISH  # opposite of trend
        decline_frac = (recent[0] - recent[-1]) / recent[0] if recent[0] > 0 else 0.0
        return self._ev(ctx, tf, ts, "momentum_decay", decline_frac, direction, decline_frac)


__all__ = ["MomentumEngine"]
