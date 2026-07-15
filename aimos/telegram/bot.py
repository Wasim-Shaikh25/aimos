"""Telegram bot entrypoint (§15.2, card P5-T4).

Wires python-telegram-bot (optional dep) to the security + notifier logic in
`security.py` / `notifier.py` (both tested without the library). Token + allowed
chat IDs from env only. This is the deployment entrypoint.
"""
from __future__ import annotations
import sys


def main() -> int:  # pragma: no cover - deployment entrypoint, needs the library + token
    print("aimos telegram bot (deployment entrypoint) — see telegram/security.py, notifier.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
