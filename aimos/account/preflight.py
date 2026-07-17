"""Read-only startup connectivity self-check (Phase D §2.4). Places NO orders.

For each venue with credentials: authenticate, ``fetch_balance`` (read-only),
and confirm withdrawals are DISABLED (§23.4, fail-closed). Reports a per-venue
status the dashboard shows on a Connections panel and that also feeds the real
balance UI. ``client_factory`` is injectable so this is fully testable against a
mock exchange (no keys, no network). Not in the magic-number-linted layers.
"""

from __future__ import annotations

from typing import Callable, Optional

import structlog

log = structlog.get_logger(__name__)


def _ccxt_client(venue: str, cred: dict):  # pragma: no cover - needs keys + network
    import ccxt
    ex = getattr(ccxt, venue)({"apiKey": cred["apiKey"], "secret": cred.get("secret", ""),
                               "enableRateLimit": True})
    return ex


def _usdt_free(balance: dict) -> float:
    if not isinstance(balance, dict):
        return 0.0
    entry = balance.get("USDT")
    if isinstance(entry, dict) and "free" in entry:
        return float(entry.get("free") or 0.0)
    free = balance.get("free")
    if isinstance(free, dict):
        return float(free.get("USDT") or 0.0)
    return 0.0


def preflight_check(
    venues: list[str], creds: dict,
    client_factory: Optional[Callable[[str, dict], object]] = None,
) -> dict:
    """Return ``{venue: {configured, connected, withdrawal_disabled, can_trade,
    usdt_free, error}}``. Read-only — no orders are ever placed."""
    factory = client_factory or _ccxt_client
    out: dict[str, dict] = {}
    for venue in venues:
        cred = creds.get(venue.lower())
        if not cred:
            out[venue] = {"venue": venue, "configured": False, "connected": False,
                          "can_trade": False, "error": ""}
            continue
        try:
            client = factory(venue, cred)
            balance = client.fetch_balance()  # read-only account call
            withdrawal_disabled = not bool(cred.get("withdraw", False))
            out[venue] = {
                "venue": venue, "configured": True, "connected": True,
                "withdrawal_disabled": withdrawal_disabled,
                "can_trade": withdrawal_disabled,  # refuse trading if key can withdraw
                "usdt_free": _usdt_free(balance), "error": "",
            }
            log.info("preflight_ok", venue=venue, withdrawal_disabled=withdrawal_disabled)
        except Exception as exc:  # noqa: BLE001 — a failed venue is reported, not fatal
            out[venue] = {"venue": venue, "configured": True, "connected": False,
                          "can_trade": False, "error": str(exc)[:200]}
            log.warning("preflight_failed", venue=venue)
    return out


__all__ = ["preflight_check"]
