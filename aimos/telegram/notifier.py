"""Telegram outbound notifications + dedupe (§15.2, card P5-T4).

Templated alerts subscribed to the event bus. Rate limit: max 1 message per
event type per symbol per 5 min (dedupe key), EXCEPT trade open/close which
always send. Risk alerts never mute. Clock-injected for deterministic tests.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from aimos.core.clock import Clock

_ALWAYS_SEND = {"trade_opened", "trade_closed"}


def fmt_trade_opened(action, symbol, plugin, entry, sl, tp, size, rr, conf, reason) -> str:
    return (f"🟢 OPENED {action} {symbol} via {plugin}\n"
            f"Entry {entry} · SL {sl} · TP {tp}\n"
            f"Size {size} · RR {rr} · Conf {conf}%\nTop reason: {reason}")


def fmt_trade_closed(symbol, exit_reason, pnl_r, pnl_quote, mae, mfe) -> str:
    return (f"🔴 CLOSED {symbol} · {exit_reason}\n"
            f"PnL {pnl_r:+.2f}R ({pnl_quote:+.2f} USDT)\nMAE {mae}R / MFE {mfe}R")


def fmt_regime_change(symbol, old, new, prob, reasons) -> str:
    return f"⚠️ {symbol} regime: {old} → {new} (p={prob}%)\n{reasons}"


def fmt_risk_alert(reason) -> str:
    return f"🚨 RISK: {reason}"


class Deduper:
    def __init__(self, clock: Clock, window_seconds: float = 300.0) -> None:
        self.clock = clock
        self.window = timedelta(seconds=window_seconds)
        self._last: dict[str, object] = {}

    def should_send(self, event_type: str, symbol: Optional[str] = None) -> bool:
        if event_type in _ALWAYS_SEND:
            return True
        key = f"{event_type}:{symbol}"
        now = self.clock.now()
        last = self._last.get(key)
        if last is not None and now - last < self.window:
            return False
        self._last[key] = now
        return True


__all__ = ["Deduper", "fmt_regime_change", "fmt_risk_alert", "fmt_trade_closed", "fmt_trade_opened"]
