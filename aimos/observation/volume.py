"""Volume engine (§5.2, card P2-T3). All math on non-synthetic candles."""

from __future__ import annotations

import numpy as np

from aimos.core.indicators import atr, sma
from aimos.core.normalize import HALF
from aimos.core.schemas import Direction, Evidence, MarketContext
from aimos.observation.base import ObservationEngine, real_candles


class VolumeEngine(ObservationEngine):
    name = "volume_engine"

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

    def _v(self) -> dict:
        return self.cfg["volume"]

    def _min_bars(self) -> int:
        v = self._v()
        return int(v["rel_vol_sma"]) + int(v["absorption_prior_bars"]) + 1

    def _ev(self, ctx, tf, ts, name, value, direction, strength, meta=None) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=tf, timestamp=ts,
            name=name, value=float(value), direction=direction,
            strength=self._clamp01(float(strength)), reliability=self.reliability, meta=meta or {},
        )

    def _observe_tf(self, ctx, tf, df) -> list[Evidence]:
        v = self._v()
        out: list[Evidence] = []
        vol = df["volume"]
        ts = df.index[-1].to_pydatetime()
        vol_sma = float(sma(vol, int(v["rel_vol_sma"])).iloc[-1])
        if vol_sma <= 0 or not np.isfinite(vol_sma):
            return out
        rel_vol = float(vol.iloc[-1]) / vol_sma
        o = float(df["open"].iloc[-1]); c = float(df["close"].iloc[-1])
        candle_dir = Direction.BULLISH if c > o else Direction.BEARISH

        # rule 1: volume spike
        if rel_vol > float(v["rel_vol_spike"]):
            strength = self._ratio_strength_vol(rel_vol)
            out.append(self._ev(ctx, tf, ts, "volume_spike", rel_vol, candle_dir, strength,
                                 {"rel_vol": rel_vol}))

        # rule 2: volume acceleration (z-scored slope of SMA(vol,accel) / SMA(vol,20))
        accel = self._accel(vol, v)
        if accel is not None:
            out.append(self._ev(ctx, tf, ts, "volume_accel", accel,
                                 Direction.BULLISH if accel > 0 else Direction.BEARISH,
                                 self._z_strength(accel)))

        # rule 3: buy/sell pressure proxy
        pressure = self._buy_pressure(ctx, tf, ts, df, v)
        if pressure is not None:
            out.append(pressure)

        # rule 4: absorption
        absorption = self._absorption(ctx, tf, ts, df, v, rel_vol)
        if absorption is not None:
            out.append(absorption)
        return out

    def _ratio_strength_vol(self, rel_vol: float) -> float:
        v = self._v()
        span = float(v["rel_vol_cap"]) - 1.0
        return min(abs(rel_vol - 1.0) / span, 1.0) if span > 0 else 0.0

    def _accel(self, vol, v):
        short = int(v["accel_short_sma"])
        long = int(v["rel_vol_sma"])
        s = sma(vol, short)
        if len(s.dropna()) <= short:
            return None
        slope = float(s.iloc[-1] - s.iloc[-1 - short])
        base = float(sma(vol, long).iloc[-1])
        if base <= 0:
            return None
        return slope / base

    def _buy_pressure(self, ctx, tf, ts, df, v):
        window = int(v["buy_frac_window"])
        recent = df.iloc[-window:]
        rng = (recent["high"] - recent["low"]).replace(0.0, np.nan)
        buy_frac = (recent["close"] - recent["low"]) / rng
        vol = recent["volume"]
        denom = float(vol.sum())
        if denom <= 0 or buy_frac.isna().all():
            return None
        vw_mean = float((buy_frac.fillna(HALF) * vol).sum() / denom)
        scale = float(v["buy_pressure_scale"])
        strength = min(abs(vw_mean - HALF) * scale, 1.0)
        if vw_mean > float(v["buy_pressure_hi"]):
            return self._ev(ctx, tf, ts, "buy_pressure", vw_mean, Direction.BULLISH, strength)
        if vw_mean < float(v["buy_pressure_lo"]):
            return self._ev(ctx, tf, ts, "buy_pressure", vw_mean, Direction.BEARISH, strength)
        return None

    def _absorption(self, ctx, tf, ts, df, v, rel_vol):
        if rel_vol <= float(v["absorption_rel_vol"]):
            return None
        atr_now = float(atr(df, int(self.cfg["volatility"]["atr_period"])).iloc[-1])
        if not np.isfinite(atr_now) or atr_now <= 0:
            return None
        o = float(df["open"].iloc[-1]); c = float(df["close"].iloc[-1])
        if abs(c - o) >= float(v["absorption_atr_frac"]) * atr_now:
            return None
        prior = int(v["absorption_prior_bars"])
        prior_move = c - float(df["close"].iloc[-1 - prior])
        # absorption acts OPPOSITE the prior push
        direction = Direction.BEARISH if prior_move > 0 else Direction.BULLISH
        strength = min(rel_vol / float(v["rel_vol_cap"]), 1.0)
        return self._ev(ctx, tf, ts, "absorption", rel_vol, direction, strength)


__all__ = ["VolumeEngine"]
