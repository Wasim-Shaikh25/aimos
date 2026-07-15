"""Broker protocol (§7.6).

``place(plan) -> OrderResult``, ``positions()``, ``equity()``, ``cancel_all(symbol)``.
PaperBroker (Phase 4) and LiveBroker (Phase 6) implement it. This is Layer-3
execution's only outward side effect.
"""

from __future__ import annotations

from typing import Protocol

from aimos.core.schemas import OrderResult, Position, TradePlan


class Broker(Protocol):
    def place(self, plan: TradePlan) -> OrderResult: ...

    def positions(self) -> list[Position]: ...

    def equity(self) -> float: ...

    def cancel_all(self, symbol: str) -> None: ...


__all__ = ["Broker"]
