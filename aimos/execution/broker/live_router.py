"""Multi-venue live arb executor (Phase D §4). GATED — off unless
``execution.multi_venue_enabled`` and the mandate is enabled.

Places the two arb legs via per-venue ``LiveBroker`` instances (buy on the cheap
venue, sell on the rich venue). Each leg is mandate-gated and withdrawal-checked
by the ``LiveBroker`` itself. If only one leg fills, the result flags
``needs_unwind`` so the caller never leaves a naked leg silently. Injectable
exchanges make this fully testable against a mock ccxt (no keys, no network). The
magic-number lint governs this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aimos.core.normalize import PCT
from aimos.core.schemas import Action, OrderResult, TradePlan
from aimos.execution.broker.live import LiveBroker

_NOMINAL_HOLD_MIN = 15  # noqa: magic — placeholder hold; an arb closes via its offsetting leg


@dataclass
class ArbLegResult:
    buy: OrderResult
    sell: OrderResult
    both_filled: bool
    needs_unwind: bool  # exactly one leg filled → the other must be unwound


def _leg(symbol: str, action: Action, price: float, notional: float) -> TradePlan:
    # SL/TP are nominal here — an arb leg is closed by its offsetting leg, not by
    # SL/TP; they only satisfy the geometry contract. 1% brackets keep rr valid.
    bracket = price / PCT
    if action is Action.LONG:
        stop, tp = price - bracket, price + bracket
    else:
        stop, tp = price + bracket, price - bracket
    return TradePlan(
        plugin="CrossExchangeArb", symbol=symbol, action=action, entry=price,
        stop_loss=stop, take_profit=tp, expected_rr=1.0, expected_hold_minutes=_NOMINAL_HOLD_MIN,
        expected_costs_bps=0.0, confidence=1.0, size_quote=notional,
        meta={"cross_venue": True, "leg": action.value},
    )


class MultiVenueLiveRouter:
    """Places both arb legs across per-venue LiveBrokers (each mandate-gated)."""

    def __init__(self, brokers: Mapping[str, LiveBroker]) -> None:
        self.brokers = dict(brokers)

    def execute_arb(
        self, base_symbol: str, buy_venue: str, sell_venue: str, notional_usd: float,
        buy_price: float, sell_price: float, total_notional_after: float,
        positions_after: int,
    ) -> ArbLegResult:
        buy_broker = self.brokers.get(buy_venue)
        sell_broker = self.brokers.get(sell_venue)
        missing = OrderResult(ok=False, status="rejected", error="venue broker missing", raw={})
        if buy_broker is None or sell_broker is None:
            return ArbLegResult(missing, missing, False, False)

        buy_res = buy_broker.place(
            _leg(base_symbol, Action.LONG, buy_price, notional_usd),
            total_notional_after, positions_after)
        sell_res = sell_broker.place(
            _leg(base_symbol, Action.SHORT, sell_price, notional_usd),
            total_notional_after, positions_after)
        both = bool(buy_res.ok and sell_res.ok)
        needs_unwind = bool(buy_res.ok) != bool(sell_res.ok)
        return ArbLegResult(buy_res, sell_res, both, needs_unwind)


__all__ = ["ArbLegResult", "MultiVenueLiveRouter"]
