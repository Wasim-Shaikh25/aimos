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
from aimos.core.schemas import Action, OrderResult, OutcomeRecord, Position, TradePlan
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
    venue: str = "paper"
    ts: Optional[datetime] = None
    pnl_quote: float = 0.0  # realized PnL on exit fills (0 on entries)
    pnl_r: float = 0.0  # R-multiple on exit fills (0 on entries)
    max_adverse_r: float = 0.0  # worst excursion in R (exit fills only)
    max_favorable_r: float = 0.0  # best excursion in R (exit fills only)
    plugin: str = ""


class PaperBroker:
    def __init__(self, starting_equity: float, cost_model: CostModel, taker: bool = True,
                 venue: str = "paper") -> None:
        self._cash = starting_equity
        self._realized = 0.0
        self.cost = cost_model
        self.taker = taker
        self.venue = venue
        self._pending: list[_Pending] = []
        self._positions: dict[str, Position] = {}
        self._states: dict[str, dict] = {}  # decision_id → {initial_risk, ...}
        self.fills: list[Fill] = []
        self.closed_trades_r: list[float] = []  # realized R-multiples for metrics
        self.pending_outcomes: list[OutcomeRecord] = []
        self._excursions: dict[str, tuple[float, float]] = {}
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

    def state_dict(self) -> dict:
        """Serialize open positions, cash, pending orders, and fill history."""
        return {
            "cash": self._cash,
            "realized": self._realized,
            "positions": [p.model_dump(mode="json") for p in self._positions.values()],
            "pending": [p.plan.model_dump(mode="json") for p in self._pending],
            "fills": [
                {
                    "decision_id": f.decision_id, "symbol": f.symbol,
                    "side": f.side.value if isinstance(f.side, Action) else f.side,
                    "qty": f.qty, "price": f.price, "fee_quote": f.fee_quote,
                    "kind": f.kind, "venue": f.venue,
                    "ts": f.ts.isoformat() if f.ts else None,
                    "pnl_quote": f.pnl_quote, "pnl_r": f.pnl_r,
                    "max_adverse_r": f.max_adverse_r, "max_favorable_r": f.max_favorable_r,
                    "plugin": f.plugin,
                }
                for f in self.fills
            ],
            "closed_trades_r": self.closed_trades_r,
            "pending_outcomes": [oc.model_dump(mode="json") for oc in self.pending_outcomes],
            "_excursions": self._excursions,
            "last_mark": self._last_mark,
        }

    def load_state(self, state: dict) -> None:
        """Restore broker state from a snapshot."""
        import json as _json
        from aimos.core.schemas import TradePlan

        self._cash = float(state.get("cash", self._cash))
        self._realized = float(state.get("realized", self._realized))
        self._positions = {}
        for p in state.get("positions", []):
            pos = Position.model_validate(p)
            self._positions[pos.symbol] = pos
        self._pending = []
        for raw in state.get("pending", []):
            plan = TradePlan.model_validate(raw)
            is_limit = plan.plugin in {"Pullback", "MeanReversion"}
            self._pending.append(_Pending(plan, is_limit))
        self.fills = []
        for raw in state.get("fills", []):
            side_raw = raw.get("side")
            side = Action(side_raw) if isinstance(side_raw, str) else side_raw
            ts = raw.get("ts")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            self.fills.append(Fill(
                decision_id=raw["decision_id"],
                symbol=raw["symbol"],
                side=side,
                qty=raw["qty"],
                price=raw["price"],
                fee_quote=raw["fee_quote"],
                kind=raw["kind"],
                venue=raw.get("venue", self.venue),
                ts=ts,
                pnl_quote=raw.get("pnl_quote", 0.0),
                pnl_r=raw.get("pnl_r", 0.0),
                max_adverse_r=raw.get("max_adverse_r", 0.0),
                max_favorable_r=raw.get("max_favorable_r", 0.0),
                plugin=raw.get("plugin", ""),
            ))
        self.closed_trades_r = [float(x) for x in state.get("closed_trades_r", [])]
        self.pending_outcomes = [OutcomeRecord.model_validate(raw) for raw in state.get("pending_outcomes", [])]
        self._excursions = {k: tuple(v) for k, v in state.get("_excursions", {}).items()}
        self._last_mark = {k: float(v) for k, v in state.get("last_mark", {}).items()}

    def cancel_all(self, symbol: str) -> None:
        self._pending = [p for p in self._pending if p.plan.symbol != symbol]

    # -- simulation driver ---------------------------------------------------

    def step(self, symbol: str, bar: dict, now: datetime, depth_usd: float = 0.0) -> None:
        """Process fills/exits against one bar (open/high/low/close)."""
        self._last_mark[symbol] = float(bar["close"])
        self._fill_pending(symbol, bar, now, depth_usd)
        self._update_excursions(symbol, bar)
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
        decision_id = plan.meta.get("decision_id") if plan.meta else None
        pos = Position(
            symbol=plan.symbol, venue="paper", side=side, qty=qty, entry=price,
            stop=plan.stop_loss or price, tp=plan.take_profit, opened_at=now,
            plugin=plan.plugin,
            decision_id=decision_id or self._order_id(plan),
            mode_tag="swing",
        )
        self._positions[plan.symbol] = pos
        self._excursions[pos.decision_id] = (0.0, 0.0)
        self.fills.append(Fill(pos.decision_id, plan.symbol, side, qty, price, fee, "entry",
                               venue=self.venue, ts=now, pnl_r=0.0, plugin=plan.plugin))

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

    def _update_excursions(self, symbol: str, bar: dict) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return
        r = abs(pos.entry - pos.stop)
        if r <= 0:
            return
        long = pos.side is Action.LONG
        low, high = float(bar["low"]), float(bar["high"])
        # Price cannot move past the position's stop or take-profit while the
        # position is open; those levels close the trade. Clamp the bar's
        # extremes to the active stop/TP so MAE/MFE are never overstated.
        if long:
            low = max(low, pos.stop)
            if pos.tp is not None:
                high = min(high, pos.tp)
            adverse = (low - pos.entry) / r
            favorable = (high - pos.entry) / r
        else:
            high = min(high, pos.stop)
            if pos.tp is not None:
                low = max(low, pos.tp)
            adverse = (pos.entry - high) / r
            favorable = (pos.entry - low) / r
        mae, mfe = self._excursions.get(pos.decision_id, (0.0, 0.0))
        self._excursions[pos.decision_id] = (min(mae, adverse), max(mfe, favorable))

    def drain_outcomes(self) -> list[OutcomeRecord]:
        """Return and clear pending outcome records."""
        out = self.pending_outcomes
        self.pending_outcomes = []
        return out

    def _close(self, pos: Position, price: float, kind: str, now) -> None:
        notional = pos.qty * price
        fee = self._fee_quote(notional)
        sign = 1.0 if pos.side is Action.LONG else -1.0
        pnl = (price - pos.entry) * pos.qty * sign - fee
        self._cash += pnl
        self._realized += pnl
        initial_risk_quote = pos.qty * abs(pos.entry - pos.stop)
        if initial_risk_quote > 0:
            pnl_r = pnl / initial_risk_quote
            self.closed_trades_r.append(pnl_r)
        else:
            pnl_r = 0.0
        mae, mfe = self._excursions.pop(pos.decision_id, (0.0, 0.0))
        self.pending_outcomes.append(OutcomeRecord(
            decision_id=pos.decision_id, exit_time=now, exit_price=price,
            pnl_r=pnl_r, pnl_quote=pnl, max_adverse_r=mae, max_favorable_r=mfe,
            exit_reason=kind,
        ))
        self.fills.append(Fill(pos.decision_id, pos.symbol, pos.side, pos.qty, price, fee, kind,
                               venue=self.venue, ts=now, pnl_quote=pnl, pnl_r=pnl_r,
                               max_adverse_r=mae, max_favorable_r=mfe, plugin=pos.plugin))
        del self._positions[pos.symbol]

    def trade_history(self) -> list[dict]:
        """Pair entry fills with their SL/TP exit into closed/open directional trades."""
        entries: dict[str, Fill] = {}
        trades: list[dict] = []
        for f in self.fills:
            if f.kind == "entry":
                entries[f.decision_id] = f
            else:  # exit (sl/tp) — pair with its entry (raw floats; UI/serve rounds)
                e = entries.pop(f.decision_id, None)
                trades.append({
                    "kind": "directional", "symbol": f.symbol, "strategy": f.plugin,
                    "venue": f.venue, "side": (e.side.value if e else f.side.value),
                    "qty": f.qty, "entry": e.price if e else None,
                    "exit": f.price, "pnl_usd": f.pnl_quote, "pnl_r": f.pnl_r,
                    "max_adverse_r": f.max_adverse_r, "max_favorable_r": f.max_favorable_r,
                    "opened_at": e.ts.isoformat() if e and e.ts else None,
                    "closed_at": f.ts.isoformat() if f.ts else None,
                    "result": f.kind, "status": "closed",
                })
        for e in entries.values():  # still-open positions
            trades.append({
                "kind": "directional", "symbol": e.symbol, "strategy": e.plugin,
                "venue": e.venue, "side": e.side.value, "qty": e.qty,
                "entry": e.price, "exit": None, "pnl_usd": 0.0, "pnl_r": 0.0,
                "max_adverse_r": 0.0, "max_favorable_r": 0.0,
                "opened_at": e.ts.isoformat() if e.ts else None, "closed_at": None,
                "result": "open", "status": "open",
            })
        return trades

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
