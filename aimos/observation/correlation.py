"""Correlation engine (§5.12, card P2-T6). Consumes ctx.candles + ctx.peers[BTC]."""

from __future__ import annotations

import numpy as np

from aimos.core.indicators import atr, beta, correlation
from aimos.core.normalize import PCT
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine, real_candles

_BTC = "BTC"


class CorrelationEngine(ObservationEngine):
    name = "correlation_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        cc = self.cfg["correlation"]
        btc = ctx.peers.get(_BTC)
        own = self._h1(ctx)
        if btc is None or own is None:
            return []
        btc = real_candles(btc)
        if len(btc) < int(cc["beta_window"]) + 1 or len(own) < int(cc["beta_window"]) + 1:
            return []

        own_ret = own["close"].pct_change().dropna().values
        btc_ret = btc["close"].pct_change().dropna().values
        n = min(len(own_ret), len(btc_ret), int(cc["beta_window"]))
        a = own_ret[-n:]
        m = btc_ret[-n:]
        b = beta(a, m)
        out: list[Evidence] = []

        # rule 1: btc_beta (meta only, NEUTRAL carrier)
        out.append(self._ev(ctx, "btc_beta", b, Direction.NEUTRAL, 0.0, {"beta": float(b)}))

        # rule 2: btc_pull — large BTC 1h move drags the alt
        btc_atr = float(atr(btc, int(self.cfg["volatility"]["atr_period"])).iloc[-1])
        btc_price = float(btc["close"].iloc[-1])
        if btc_atr > 0 and btc_price > 0:
            atr_pct = btc_atr / btc_price * PCT
            btc_ret_1h = float(btc["close"].iloc[-1] / btc["close"].iloc[-2] - 1.0) * PCT
            if abs(btc_ret_1h) > float(cc["btc_pull_atr_mult"]) * atr_pct:
                z = btc_ret_1h / atr_pct if atr_pct > 0 else 0.0
                direction = Direction.BULLISH if btc_ret_1h > 0 else Direction.BEARISH
                out.append(self._ev(ctx, "btc_pull", btc_ret_1h, direction,
                                    self._z_strength(z * b), {"btc_return_pct": btc_ret_1h}))

        # rule 3: decoupling
        short = int(cc["decoupling_short_window"])
        long = int(cc["decoupling_long_window"])
        corr_short = correlation(a[-short:], m[-short:])
        corr_long = correlation(a[-long:], m[-long:])
        if corr_short < float(cc["decoupling_short_thresh"]) and corr_long > float(cc["decoupling_long_thresh"]):
            out.append(self._ev(ctx, "decoupling", corr_short, Direction.NEUTRAL,
                                self._clamp01(1 - corr_short),
                                {"corr_short": corr_short, "corr_long": corr_long, "idiosyncratic": True}))
        return out

    def _h1(self, ctx):
        for tf in (Timeframe.H1, Timeframe.M15, Timeframe.M5):
            df = ctx.candles.get(tf)
            if df is not None and not df.empty:
                return real_candles(df)
        return None

    def _ev(self, ctx, name, value, direction, strength, meta) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.H1,
            timestamp=ctx.now, name=name, value=float(value), direction=direction,
            strength=self._clamp01(float(strength)), reliability=self.reliability, meta=meta,
        )


__all__ = ["CorrelationEngine"]
