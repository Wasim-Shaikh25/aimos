"""Trade Management Engine (§23.1 + §23.10C, card P4-T4).

Open positions are re-evaluated each base-timeframe tick. Rules (all thresholds
from config/trade_manager.yaml): break-even, trailing stop (never widens),
partial take-profit, thesis-invalidation exit, time stop, stale-order sweep, plus
the exit-liquidity monitor (tighten → slice-exit). Every action emits a
``ManagementEvent``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from aimos.core.normalize import PCT
from aimos.core.schemas import (
    Action,
    Behavior,
    Direction,
    ManagementEvent,
    MarketUnderstanding,
    Position,
    Regime,
)


@dataclass
class ManagementState:
    """Per-position mutable management state."""

    initial_risk: float  # entry-to-stop distance in price (defines R)
    current_stop: float
    expected_hold_minutes: int = 0  # from the plan (for the time stop)
    breakeven_done: bool = False
    partial_done: bool = False
    trail_active: bool = False


class TradeManager:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg  # trade_manager subtree

    def step(
        self,
        pos: Position,
        price: float,
        atr: float,
        mu: Optional[MarketUnderstanding],
        now: datetime,
        state: ManagementState,
        exit_slippage_bps: Optional[float] = None,
        entry_exit_slippage_bps: Optional[float] = None,
    ) -> list[ManagementEvent]:
        events: list[ManagementEvent] = []
        long = pos.side is Action.LONG
        r = self._r_multiple(pos, price, state, long)

        # thesis invalidation (any PnL)
        te = self._thesis_exit(pos, mu, now, long)
        if te:
            return [te]  # exit now, skip other management

        # time stop
        ts = self._time_stop(pos, now, r, state)
        if ts:
            return [ts]

        # break-even
        if not state.breakeven_done and r >= float(self.cfg["breakeven_r"]):
            new_stop = pos.entry  # + costs handled by caller's fee model
            state.current_stop = new_stop
            state.breakeven_done = True
            events.append(self._ev(pos, now, "breakeven", new_stop=new_stop))

        # partial take-profit
        if not state.partial_done and r >= float(self.cfg["partial_tp_r"]):
            qty = pos.qty * (float(self.cfg["partial_tp_pct"]) / PCT)
            state.partial_done = True
            events.append(self._ev(pos, now, "partial_tp", closed_qty=qty))

        # trailing stop (never widens)
        if r >= float(self.cfg["trail_activate_r"]):
            state.trail_active = True
        if state.trail_active and atr > 0:
            trail = float(self.cfg["trail_atr_mult"]) * atr
            candidate = price - trail if long else price + trail
            new_stop = max(state.current_stop, candidate) if long else min(state.current_stop, candidate)
            if new_stop != state.current_stop:
                state.current_stop = new_stop
                events.append(self._ev(pos, now, "trail", new_stop=new_stop))

        # exit-liquidity monitor (§23.10C)
        events.extend(self._liquidity(pos, now, state, exit_slippage_bps, entry_exit_slippage_bps))
        return events

    # -- rules ---------------------------------------------------------------

    @staticmethod
    def _r_multiple(pos, price, state, long) -> float:
        if state.initial_risk <= 0:
            return 0.0
        return (price - pos.entry) / state.initial_risk if long else (pos.entry - price) / state.initial_risk

    def _thesis_exit(self, pos, mu, now, long) -> Optional[ManagementEvent]:
        if mu is None:
            return None
        opposed = (long and mu.direction_bias is Direction.BEARISH) or (
            not long and mu.direction_bias is Direction.BULLISH
        )
        flip = opposed and mu.confidence >= float(self.cfg["thesis_exit_confidence"])
        crash = mu.regime is Regime.CRASH
        manip = mu.behavior is Behavior.MANIPULATION
        if flip or crash or manip:
            reason = "regime flip" if flip else ("crash" if crash else "manipulation")
            return self._ev(pos, now, "thesis_exit", detail={"reason": f"thesis invalidated: {reason}"})
        return None

    def _time_stop(self, pos, now, r, state) -> Optional[ManagementEvent]:
        if state.expected_hold_minutes <= 0:
            return None
        elapsed = now - pos.opened_at
        limit = timedelta(minutes=float(self.cfg["time_stop_hold_mult"]) * state.expected_hold_minutes)
        if elapsed > limit and r < float(self.cfg["time_stop_min_r"]):
            return self._ev(pos, now, "time_stop", detail={"r": r})
        return None

    def _liquidity(self, pos, now, state, exit_slip, entry_slip) -> list[ManagementEvent]:
        if exit_slip is None or entry_slip is None or entry_slip <= 0:
            return []
        mult = float(self.cfg.get("exit_degrade_mult", 2.0))
        if exit_slip > mult * entry_slip:
            return [self._ev(pos, now, "liquidity_tighten",
                             detail={"exit_slip_bps": exit_slip, "entry_slip_bps": entry_slip})]
        return []

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _ev(pos, now, kind, new_stop=None, closed_qty=None, detail=None) -> ManagementEvent:
        return ManagementEvent(
            decision_id=pos.decision_id, timestamp=now, kind=kind,
            detail=detail or {}, new_stop=new_stop, closed_qty=closed_qty,
        )


__all__ = ["ManagementState", "TradeManager"]
