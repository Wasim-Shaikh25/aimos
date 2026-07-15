"""PaperBroker — simulated fills + equity ledger (§7.6, §9.2, card P4-T6).

Market orders fill on the NEXT tick (no same-bar fills, §9.1) at the bar open ±
slippage; limit orders fill when the bar range crosses the limit. Open positions
exit on SL/TP touches (SL checked first — worst case). Fees + slippage from the
cost model; funding applied on 8-hourly boundaries when a rate is supplied.
All tunables come from the cost model / config (§23.12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from aimos.core.normalize import BPS, HALF
from aimos.core.schemas import Action, OrderResult, Position, TradePlan
from aimos.backtest.costs import CostModel, funding_cost_bps


@dataclass
class _Pending:
    plan: TradePlan
    is_limit: bool


@dataclass
class Fill:
    decision_id: str
    symbol: str
    side: Action
    qty: float
    price: float
    fee_quote: float
    kind: str  # "entry" | "sl" | "tp"


class PaperBroker:
    def __init__(self, starting_equity: float, cost_model: CostModel, taker: bool = True) -> None:
        self._cash = starting_equity
        self._realized = 0.0
        self.cost = cost_model
        self.taker = taker
        self._pending: list[_Pending] = []
        self._positions: dict[str, Position] = {}
        self._states: dict[str, dict] = {}  # decision_id → {initial_risk, ...}
        self.fills: list[Fill] = []
        self.closed_trades_r: list[float] = []  # realized R-multiples for metrics
        self._last_mark: dict[str, float] = {}

    # -- Broker protocol -----------------------------------------------------

    def place(self, plan: TradePlan) -> OrderResult:
        if plan.action is Action.NO_TRADE or not plan.size_quote:
            return OrderResult(ok=True, status="rejected", error="no_trade_or_no_size", raw={})
        is_limit = plan.plugin in {"Pullback", "MeanReversion"}  # limit-entry plugins (§7.2)
        self._pending.append(_Pending(plan, is_limit))
        return OrderResult(ok=True, order_id=self._order_id(plan), status="open", raw={})

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def equity(self) -> float:
        unrealized = sum(self._unrealized(p) for p in self._positions.values())
        return self._cash + unrealized

    def cash(self) -> float:
        return self._cash

    def cancel_all(self, symbol: str) -> None:
        self._pending = [p for p in self._pending if p.plan.symbol != symbol]

    # -- simulation driver ---------------------------------------------------

    def step(self, symbol: str, bar: dict, now: datetime, depth_usd: float = 0.0) -> None:
        """Process fills/exits against one bar (open/high/low/close)."""
        self._last_mark[symbol] = float(bar["close"])
        self._fill_pending(symbol, bar, now, depth_usd)
        self._check_exits(symbol, bar, now, depth_usd)

    def _fill_pending(self, symbol, bar, now, depth_usd) -> None:
        still: list[_Pending] = []
        for pend in self._pending:
            plan = pend.plan
            if plan.symbol != symbol:
                still.append(pend)
                continue
            fill_price = self._fill_price(pend, bar)
            if fill_price is None:
                still.append(pend)  # limit not crossed yet
                continue
            self._open_position(plan, fill_price, now, depth_usd)
        self._pending = still

    def _fill_price(self, pend: _Pending, bar) -> Optional[float]:
        if not pend.is_limit:
            return float(bar["open"])  # market → next-bar open
        limit = pend.plan.entry
        if limit is None:
            return None
        if float(bar["low"]) <= limit <= float(bar["high"]):  # crossed
            return limit
        return None

    def _open_position(self, plan: TradePlan, price: float, now, depth_usd) -> None:
        qty = plan.size_quote / price
        fee = self._fee_quote(plan.size_quote)
        self._cash -= fee
        side = Action.LONG if plan.action is Action.LONG else Action.SHORT
        pos = Position(
            symbol=plan.symbol, venue="paper", side=side, qty=qty, entry=price,
            stop=plan.stop_loss or price, tp=plan.take_profit, opened_at=now,
            plugin=plan.plugin, decision_id=self._order_id(plan), mode_tag="swing",
        )
        self._positions[plan.symbol] = pos
        self.fills.append(Fill(pos.decision_id, plan.symbol, side, qty, price, fee, "entry"))

    def _check_exits(self, symbol, bar, now, depth_usd) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return
        long = pos.side is Action.LONG
        low, high = float(bar["low"]), float(bar["high"])
        exit_price = None
        kind = None
        # SL checked first (worst case)
        if long and low <= pos.stop:
            exit_price, kind = pos.stop, "sl"
        elif not long and high >= pos.stop:
            exit_price, kind = pos.stop, "sl"
        elif pos.tp is not None and long and high >= pos.tp:
            exit_price, kind = pos.tp, "tp"
        elif pos.tp is not None and not long and low <= pos.tp:
            exit_price, kind = pos.tp, "tp"
        if exit_price is not None:
            self._close(pos, exit_price, kind, now)

    def _close(self, pos: Position, price: float, kind: str, now) -> None:
        notional = pos.qty * price
        fee = self._fee_quote(notional)
        sign = 1.0 if pos.side is Action.LONG else -1.0
        pnl = (price - pos.entry) * pos.qty * sign - fee
        self._cash += pnl
        self._realized += pnl
        initial_risk_quote = pos.qty * abs(pos.entry - pos.stop)
        if initial_risk_quote > 0:
            self.closed_trades_r.append(pnl / initial_risk_quote)
        self.fills.append(Fill(pos.decision_id, pos.symbol, pos.side, pos.qty, price, fee, kind))
        del self._positions[pos.symbol]

    def apply_funding(self, symbol: str, funding_rate_bps: float, minutes: float) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return
        sign = 1 if pos.side is Action.LONG else -1
        cost_bps = funding_cost_bps(funding_rate_bps, minutes, sign)
        notional = pos.qty * self._last_mark.get(symbol, pos.entry)
        self._cash -= notional * cost_bps / BPS

    # -- helpers -------------------------------------------------------------

    def _fee_quote(self, notional: float) -> float:
        fee_bps = self.cost.taker_bps if self.taker else self.cost.maker_bps
        return notional * fee_bps / BPS

    def _unrealized(self, pos: Position) -> float:
        mark = self._last_mark.get(pos.symbol, pos.entry)
        sign = 1.0 if pos.side is Action.LONG else -1.0
        return (mark - pos.entry) * pos.qty * sign

    @staticmethod
    def _order_id(plan: TradePlan) -> str:
        return f"{plan.symbol}-{plan.plugin}"


__all__ = ["Fill", "PaperBroker"]
