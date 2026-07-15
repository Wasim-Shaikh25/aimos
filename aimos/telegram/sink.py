"""Telegram outbound sink (§15.2, card P5-T4 wiring).

Sends messages via the Telegram Bot API with a plain HTTPS POST — no
python-telegram-bot dependency needed for OUTBOUND alerts, just a bot token.
Subscribes to the event bus and formats trade/decision/risk events. In dry-run
mode (no token) it logs the message so you can see the loop working without a
token. Not in the linted layers.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog

from aimos.core.bus import EventBus, Topic

log = structlog.get_logger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramSink:
    def __init__(self, token: Optional[str] = None, allowed_ids: Optional[list[int]] = None,
                 dry_run: bool = False) -> None:
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
        ids_env = os.environ.get("TELEGRAM_ALLOWED_IDS", "")
        self.allowed_ids = allowed_ids or [int(x) for x in ids_env.split(",") if x.strip()]
        self.dry_run = dry_run or not self.token
        self.sent: list[str] = []  # captured messages (for tests / dry-run)

    def send(self, text: str) -> None:
        self.sent.append(text)
        if self.dry_run:
            log.info("telegram_dry_run", message=text)
            return
        try:
            import httpx  # lazy — only needed for real sends
            for chat_id in self.allowed_ids:
                httpx.post(_API.format(token=self.token),
                           json={"chat_id": chat_id, "text": text}, timeout=10.0)
        except Exception:  # noqa: BLE001 — never let a notify failure break the loop
            log.exception("telegram_send_failed")

    # -- event-bus wiring ----------------------------------------------------

    def attach(self, bus: EventBus) -> None:
        bus.subscribe(Topic.TRADE_OPENED, self._on_trade_opened)
        bus.subscribe(Topic.TRADE_CLOSED, self._on_trade_closed)
        bus.subscribe(Topic.RISK_ALERT, self._on_risk_alert)

    def _on_trade_opened(self, topic: Topic, payload: dict) -> None:
        self.send(f"🟢 OPENED {payload.get('symbol')} via {payload.get('plan')}")

    def _on_trade_closed(self, topic: Topic, payload: dict) -> None:
        self.send(f"🔴 CLOSED {payload.get('symbol')} · {payload.get('exit_reason', '')}")

    def _on_risk_alert(self, topic: Topic, payload: dict) -> None:
        self.send(payload.get("message", f"🚨 RISK: {payload}"))


__all__ = ["TelegramSink"]
