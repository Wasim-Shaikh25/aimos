"""Time engine (§5.13, card P2-T5). Pure context, all NEUTRAL, low reliability."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


class TimeEngine(ObservationEngine):
    name = "time_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        tc = self.cfg["time"]
        now = ctx.now
        hour = now.hour
        out: list[Evidence] = []

        # session by UTC hour boundaries (meta)
        session = self._session(hour, tc["session_bounds"])
        out.append(self._ev(ctx, "session", hour, {"session": session}))

        # weekend flag
        if now.weekday() in set(tc["weekend_weekdays"]):
            out.append(self._ev(ctx, "weekend", now.weekday(),
                                 {"risk_add": float(tc["weekend_risk_add"])}))

        # funding window: within N minutes of a settlement hour
        if self._near_funding(now, tc):
            out.append(self._ev(ctx, "funding_window", hour, {"near_settlement": True}))
        return out

    @staticmethod
    def _session(hour: int, bounds: list[int]) -> str:
        _day_start, asia_end, eu_end, us_end = bounds
        if hour < asia_end:
            return "asia"
        if hour < eu_end:
            return "europe"
        if hour < us_end:
            return "us"
        return "asia"  # 22-24 UTC rolls into the asia session

    @staticmethod
    def _near_funding(now, tc) -> bool:
        window = timedelta(minutes=int(tc["funding_window_min"]))
        day = now.date()
        for h in tc["funding_settlement_hours"]:
            settle = datetime.combine(day, time(hour=int(h)), tzinfo=now.tzinfo)
            # check the settlement today and its neighbours across the midnight wrap
            for s in (settle - timedelta(days=1), settle, settle + timedelta(days=1)):
                if abs(now - s) <= window:
                    return True
        return False

    def _ev(self, ctx, name, value, meta) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.H1,
            timestamp=ctx.now, name=name, value=float(value), direction=Direction.NEUTRAL,
            strength=0.0, reliability=self.reliability, meta=meta,
        )


__all__ = ["TimeEngine"]
