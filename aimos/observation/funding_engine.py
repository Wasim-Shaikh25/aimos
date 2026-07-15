"""Funding engine (§5.7, card P2-T5). Consumes ctx.funding (ts, rate, oi)."""

from __future__ import annotations

import numpy as np

from aimos.core.indicators import zscore_last
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


class FundingEngine(ObservationEngine):
    name = "funding_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        fdf = ctx.funding
        if fdf is None or len(fdf) < 2:
            return []
        fc = self.cfg["funding"]
        ts = ctx.now
        out: list[Evidence] = []
        rate = fdf["rate"].astype(float).values

        # rule 1: funding extreme (contrarian — opposite of funding sign)
        hist = rate[-int(fc["hist_window"]):]
        z = zscore_last(hist)
        if abs(z) > float(fc["z_extreme"]):
            funding_sign = np.sign(rate[-1])
            direction = Direction.BEARISH if funding_sign > 0 else Direction.BULLISH
            out.append(self._ev(ctx, ts, "funding_extreme", z, direction,
                                 self._z_strength(z), self.reliability))

        # rule 2: funding trend (confirmation, lower reliability)
        trend_n = int(fc["trend_periods"])
        if len(rate) > trend_n:
            slope = float(rate[-1] - rate[-1 - trend_n])
            if slope != 0:
                out.append(self._ev(ctx, ts, "funding_trend", slope,
                                     Direction.BULLISH if slope > 0 else Direction.BEARISH,
                                     self._z_strength(zscore_last(rate[-int(fc["hist_window"]):])),
                                     self.reliability * float(fc["trend_reliability_mult"])))

        # rule 3: OI divergence
        if "oi" in fdf.columns and fdf["oi"].notna().sum() >= 2:
            out.extend(self._oi_divergence(ctx, ts, fdf, fc))
        return out

    def _oi_divergence(self, ctx, ts, fdf, fc) -> list[Evidence]:
        oi = fdf["oi"].astype(float)
        # price proxy: use rate frame's paired price if present else skip
        if "price" not in fdf.columns:
            return []
        price = fdf["price"].astype(float)
        d_price = float(price.iloc[-1] - price.iloc[-2])
        d_oi = float(oi.iloc[-1] - oi.iloc[-2])
        if d_price == 0 or d_oi == 0:
            return []
        # price up + OI up → bullish (new money); price up + OI down → bearish
        if d_price > 0:
            direction = Direction.BULLISH if d_oi > 0 else Direction.BEARISH
        else:
            direction = Direction.BEARISH if d_oi > 0 else Direction.BULLISH
        z = zscore_last(oi.diff().dropna().values)
        return [self._ev(ctx, ts, "oi_divergence", d_oi, direction, self._z_strength(z),
                         self.reliability)]

    def _ev(self, ctx, ts, name, value, direction, strength, reliability) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.H1,
            timestamp=ts, name=name, value=float(value), direction=direction,
            strength=self._clamp01(float(strength)), reliability=reliability, meta={},
        )


__all__ = ["FundingEngine"]
