"""Telegram security — whitelist + nonce confirmation (§15.2, card P5-T4).

Non-negotiable rules: every update's chat_id is checked against the allowlist
(unknown → ignored silently, attempt logged); dangerous commands use a two-step
nonce flow (nonce expires in 60s; only the original chat may confirm). No
Telegram command can raise config caps or enable live mode. Clock-injected for
deterministic expiry tests.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import structlog

from aimos.core.clock import Clock

log = structlog.get_logger(__name__)

DANGEROUS_COMMANDS = {"/flatten", "/flattenall", "/killswitch", "/setrisk", "/tiercap",
                      "/disable", "/enable", "/approve", "/reject", "/scalp"}


class ChatWhitelist:
    def __init__(self, allowed_ids: set[int]) -> None:
        self.allowed = set(allowed_ids)

    def is_allowed(self, chat_id: int) -> bool:
        ok = chat_id in self.allowed
        if not ok:
            log.warning("telegram_unauthorized", chat_id=chat_id)
        return ok


@dataclass
class _PendingConfirm:
    chat_id: int
    command: str
    expires_at: datetime


class NonceStore:
    def __init__(self, clock: Clock, ttl_seconds: float = 60.0) -> None:
        self.clock = clock
        self.ttl = timedelta(seconds=ttl_seconds)
        self._pending: dict[str, _PendingConfirm] = {}

    def create(self, chat_id: int, command: str) -> str:
        nonce = secrets.token_hex(4)
        self._pending[nonce] = _PendingConfirm(chat_id, command, self.clock.now() + self.ttl)
        return nonce

    def confirm(self, chat_id: int, nonce: str) -> tuple[bool, Optional[str]]:
        """Return (ok, command). Fails on unknown/expired nonce or wrong chat."""
        pend = self._pending.get(nonce)
        if pend is None:
            return False, None
        if self.clock.now() > pend.expires_at:
            del self._pending[nonce]
            return False, None
        if pend.chat_id != chat_id:  # only the original chat may confirm
            return False, None
        del self._pending[nonce]
        return True, pend.command

    def is_dangerous(self, command: str) -> bool:
        return command.split()[0] in DANGEROUS_COMMANDS


__all__ = ["ChatWhitelist", "DANGEROUS_COMMANDS", "NonceStore"]
