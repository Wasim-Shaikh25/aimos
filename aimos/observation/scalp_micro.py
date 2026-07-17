"""ScalpMicroEngine — proxy fast-loop micro context (§17.2, feature-flagged).

The real fast loop derives scalp micro signals (1m ATR, book imbalance, top-of-
book, volume spike) from a 1m candle + order-book STREAM. That stream isn't
present in the slow paper/serve loop, so — only when scalping is enabled — this
engine derives PROXY micro signals from the available candles so ``MomentumScalp``
can run and be demonstrable in paper mode. It surfaces them in
``key_levels['scalp']`` (merged by the intelligence layer). Live scalping replaces
this with the real streaming micro-context. Thresholds come from
``observation.yaml scalp_micro`` (§23.12).
"""

from __future__ import annotations

from aimos.core.indicators import atr
from aimos.core.normalize import BPS, HALF
from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


class ScalpMicroEngine(ObservationEngine):
    name = "scalp_micro_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        cfg = self.cfg.get("scalp_micro")
        if not cfg or not ctx.candles:
            return []
        tf = sorted(ctx.candles, key=lambda t: _tf_minutes(t))[0]  # finest available
        df = ctx.candles[tf]
        window = int(cfg["window"])
        if df is None or len(df) < window:
            return []
        last = df.iloc[-1]
        close, openp = float(last["close"]), float(last["open"])
        high, low = float(last["high"]), float(last["low"])
        rng = high - low
        atr_val = float(atr(df, int(cfg["atr_period"])).iloc[-1])
        spread_bps = float(cfg["nominal_spread_bps"])
        half = close * spread_bps * HALF / BPS
        vols = df["volume"].to_numpy()[-window:]
        vol_spike = bool(vols[-1] > vols.mean() * float(cfg["vol_spike_mult"]))
        imbalance = ((close - openp) / rng) if rng > 0 else 0.0  # proxy book imbalance
        scalp = {
            "spread_bps": spread_bps, "atr1m": atr_val, "book_imbalance": imbalance,
            "volume_spike": vol_spike, "best_bid": close - half, "best_ask": close + half,
        }
        return [Evidence(
            source=f"{self.name}.scalp_micro", symbol=ctx.symbol, timeframe=Timeframe.M1,
            timestamp=ctx.now, name="factor_scalp_micro", value=imbalance,
            direction=Direction.NEUTRAL, strength=min(abs(imbalance), 1.0),
            reliability=self.reliability, meta={"key_levels": {"scalp": scalp}},
        )]


def _tf_minutes(tf: Timeframe) -> int:  # timeframe → minutes (structural, not tunable)
    return {Timeframe.M1: 1, Timeframe.M5: 5, Timeframe.M15: 15,  # noqa: magic
            Timeframe.H1: 60, Timeframe.H4: 240, Timeframe.D1: 1440}.get(tf, 60)  # noqa: magic


__all__ = ["ScalpMicroEngine"]
