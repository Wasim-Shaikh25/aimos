"""Volatility engine (§5.4, card P2-T4). All evidence NEUTRAL (context/risk)."""

from __future__ import annotations

import numpy as np

from aimos.core.indicators import atr, true_range
from aimos.core.schemas import Direction, Evidence, MarketContext
from aimos.observation.base import ObservationEngine, real_candles


class VolatilityEngine(ObservationEngine):
    name = "volatility_engine"

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

    def _vol(self) -> dict:
        return self.cfg["volatility"]

    def _min_bars(self) -> int:
        return int(self._vol()["atr_long_period"]) + 1

    def _ev(self, ctx, tf, ts, name, value, strength, meta=None) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=tf, timestamp=ts,
            name=name, value=float(value), direction=Direction.NEUTRAL,
            strength=self._clamp01(float(strength)), reliability=self.reliability, meta=meta or {},
        )

    def _observe_tf(self, ctx, tf, df) -> list[Evidence]:
        vc = self._vol()
        ts = df.index[-1].to_pydatetime()
        atr_s = float(atr(df, int(vc["atr_period"])).iloc[-1])
        atr_l = float(atr(df, int(vc["atr_long_period"])).iloc[-1])
        if not (np.isfinite(atr_s) and np.isfinite(atr_l)) or atr_l <= 0:
            return []
        out: list[Evidence] = []
        ratio = atr_s / atr_l

        # rule 1: ATR exported in meta on every emitted evidence (and a carrier)
        atr_meta = {"atr": atr_s, "atr_ratio": ratio}

        # rule 2: compression
        comp = float(vc["compression_ratio"])
        if ratio < comp:
            out.append(self._ev(ctx, tf, ts, "vol_compression", ratio,
                                 1 - ratio / comp, atr_meta))
        # rule 3: expansion
        exp = float(vc["expansion_ratio"])
        if ratio > exp:
            out.append(self._ev(ctx, tf, ts, "vol_expansion", ratio,
                                 self._ratio_strength(ratio), atr_meta))

        # rule 4: volatility shock — single-bar TR > shock_tr_mult × ATR
        tr_now = float(true_range(df).iloc[-1])
        if tr_now > float(vc["shock_tr_mult"]) * atr_s and atr_s > 0:
            o = float(df["open"].iloc[-1]); c = float(df["close"].iloc[-1])
            bar_dir = "up" if c >= o else "down"
            out.append(self._ev(ctx, tf, ts, "vol_shock", tr_now / atr_s,
                                 self._z_strength(tr_now / atr_s),
                                 {**atr_meta, "bar_direction": bar_dir, "risk_gate": True}))
        return out


__all__ = ["VolatilityEngine"]
