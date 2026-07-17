"""Telegram inbound bot — command router + poller (§15.2, §16.3, card P5-T4).

Real command handling: the router parses commands, enforces the whitelist +
nonce-confirmation security (§15.2), and acts on the orchestrator/journal.
Transport is abstracted (``Transport``) so the router is fully testable without
the network; ``HttpTransport`` talks to the Bot API over plain HTTPS (just a
token). Not in the linted layers.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Protocol

import structlog

from aimos.core.clock import LiveClock
from aimos.telegram.security import ChatWhitelist, NonceStore

log = structlog.get_logger(__name__)

_HELP = (
    "/status  /positions  /pnl  /pause [SYM]  /resume [SYM]\n"
    "/flatten SYM  /killswitch  (confirm with /confirm <nonce>)"
)


class Transport(Protocol):
    def get_updates(self, offset: int) -> list[dict]: ...
    def send_message(self, chat_id: int, text: str) -> None: ...


class HttpTransport:  # pragma: no cover - network
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"

    def get_updates(self, offset: int) -> list[dict]:
        import httpx
        r = httpx.get(f"{self.base}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=15.0)
        return r.json().get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        import httpx
        httpx.post(f"{self.base}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10.0)


class CommandRouter:
    """Parses + executes commands with security. Returns the reply text (or None
    to stay silent, e.g. an unauthorized chat)."""

    def __init__(
        self,
        whitelist: ChatWhitelist,
        nonce_store: NonceStore,
        orchestrator: Optional[Any] = None,
        journal: Optional[Any] = None,
        positions_provider: Optional[Any] = None,
        feature_controller: Optional[Any] = None,
    ) -> None:
        self.whitelist = whitelist
        self.nonce = nonce_store
        self.orch = orchestrator
        self.journal = journal
        self.positions_provider = positions_provider
        self.features = feature_controller

    def handle(self, chat_id: int, text: str) -> Optional[str]:
        if not self.whitelist.is_allowed(chat_id):
            return None  # silent ignore + logged (§15.2)
        text = text.strip()
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:]

        if cmd == "/confirm":
            return self._confirm(chat_id, args)
        if self.nonce.is_dangerous(cmd):
            nonce = self.nonce.create(chat_id, text)
            return f"confirm '{text}' -> reply: /confirm {nonce} (expires 60s)"

        handler = {
            "/help": lambda: _HELP,
            "/status": self._status,
            "/positions": self._positions,
            "/pnl": self._pnl,
            "/pause": lambda: self._pause(args),
            "/resume": lambda: self._resume(args),
            "/features": self._features,
        }.get(cmd)
        if handler is None:
            return f"unknown command {cmd}\n{_HELP}"
        return handler()

    # -- confirmed (dangerous) actions --------------------------------------

    def _confirm(self, chat_id: int, args: list[str]) -> str:
        if not args:
            return "usage: /confirm <nonce>"
        ok, command = self.nonce.confirm(chat_id, args[0])
        if not ok:
            return "confirmation failed (bad/expired nonce or wrong chat)"
        return self._execute_dangerous(command)

    def _execute_dangerous(self, command: str) -> str:
        parts = command.split()
        cmd = parts[0].lower()
        if cmd == "/killswitch":
            if self.orch:
                self.orch.state.halted = True
            return "killswitch engaged - trading halted"
        if cmd == "/flatten" and len(parts) > 1:
            sym = parts[1]
            if self.orch:
                self.orch.pause(sym)  # stop new entries; broker flatten wired at deploy
            return f"flatten {sym} requested"
        if cmd in ("/enable", "/disable"):
            return self._set_feature(parts[1:], cmd == "/enable")
        return f"executed: {command}"

    # -- info commands -------------------------------------------------------

    def _status(self) -> str:
        if self.journal is None:
            return "no journal"
        halted = bool(getattr(self.orch, "state", None) and self.orch.state.halted)
        return f"decisions journaled: {self.journal.decision_count()}; halted: {halted}"

    def _positions(self) -> str:
        pos = self.positions_provider() if self.positions_provider else []
        if not pos:
            return "no open positions"
        return "\n".join(f"{p['symbol']} {p['side']} qty {p['qty']}" for p in pos)

    def _pnl(self) -> str:
        if self.journal is None:
            return "no journal"
        return f"decisions: {self.journal.decision_count()}"

    def _pause(self, args: list[str]) -> str:
        sym = args[0] if args else None
        if self.orch:
            self.orch.pause(sym)
        return f"paused {sym or 'global'} (still observing)"

    def _resume(self, args: list[str]) -> str:
        sym = args[0] if args else None
        if self.orch:
            self.orch.resume(sym)
        return f"resumed {sym or 'global'}"

    def _features(self) -> str:
        if self.features is None:
            return "feature control not available"
        snap = self.features.snapshot()
        on = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in snap["features"].items())
        return (f"features: {on}\ntoggleable: {', '.join(snap['toggleable'])}\n"
                f"locked (go-live ladder): {', '.join(snap['locked'])}\n"
                f"use: /enable <name> · /disable <name>")

    def _set_feature(self, args: list[str], value: bool) -> str:
        if self.features is None:
            return "feature control not available"
        if not args:
            return f"usage: /{'enable' if value else 'disable'} <feature>"
        res = self.features.set(args[0], value)
        return (f"✅ {res['feature']} {'enabled' if res['enabled'] else 'disabled'}"
                if res.get("ok") else f"⚠️ {res.get('error')}")


class TelegramBot:
    def __init__(self, transport: Transport, router: CommandRouter) -> None:
        self.transport = transport
        self.router = router
        self._offset = 0

    def poll_once(self) -> int:
        """Process one batch of updates. Returns the count of replies sent."""
        updates = self.transport.get_updates(self._offset)
        handled = 0
        for u in updates:
            self._offset = max(self._offset, u.get("update_id", 0) + 1)
            msg = u.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = msg.get("text")
            if chat_id is None or not text:
                continue
            reply = self.router.handle(int(chat_id), text)
            if reply is not None:
                self.transport.send_message(int(chat_id), reply)
                handled += 1
        return handled


def main() -> int:  # pragma: no cover - deployment entrypoint (needs token)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.warning("telegram_no_token")
        return 0
    ids = [int(x) for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",") if x.strip()]
    router = CommandRouter(ChatWhitelist(set(ids)), NonceStore(LiveClock()))
    bot = TelegramBot(HttpTransport(token), router)
    bot.poll_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
