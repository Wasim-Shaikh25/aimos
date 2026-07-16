"""Large-print detection from the public trade feed (§5.8 phase-1 part, card P1-T3).

Phase 1 whale source: single trade prints above a USD threshold. A ``WhaleSource``
protocol keeps the interface identical to later netflow sources (§5.8 Phase 3),
so activation is a config flag. Aggregation into evidence happens in the whale
observation engine (§5.8); here we only detect prints and net their flow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence

from aimos.core.schemas import Direction, LargePrint


class WhaleSource(Protocol):
    """Source of raw public trades (ccxt ``fetch_trades`` shape)."""

    def fetch_trades(self, symbol: str, since: int | None, limit: int) -> list[dict]:
        ...


def detect_large_prints(
    trades: Sequence[dict],
    symbol: str,
    min_notional_usd: float,
) -> list[LargePrint]:
    """Filter a trade list down to prints ≥ ``min_notional_usd``.

    Each trade dict uses ccxt keys: ``timestamp`` (ms), ``price``, ``amount``,
    ``side`` ("buy"/"sell"). Notional = price × amount.
    """
    out: list[LargePrint] = []
    for t in trades:
        price = float(t["price"])
        amount = float(t["amount"])
        notional = price * amount
        if notional < min_notional_usd:
            continue
        side = Direction.BULLISH if t.get("side") == "buy" else Direction.BEARISH
        ts = datetime.fromtimestamp(int(t["timestamp"]) / 1000.0, tz=timezone.utc)
        out.append(
            LargePrint(
                timestamp=ts,
                symbol=symbol,
                side=side,
                notional_usd=notional,
                price=price,
            )
        )
    return out


def net_flow_usd(
    prints: Sequence[LargePrint],
    now: datetime,
    window_minutes: int,
) -> float:
    """Net large-print flow (buys − sells) in USD over the trailing window (§5.8)."""
    cutoff = now - timedelta(minutes=window_minutes)
    net = 0.0
    for p in prints:
        if p.timestamp < cutoff:
            continue
        net += p.notional_usd if p.side == Direction.BULLISH else -p.notional_usd
    return net


__all__ = ["WhaleSource", "detect_large_prints", "net_flow_usd"]
