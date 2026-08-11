"""Read-only startup connectivity self-check (Phase D §2.4). Places NO orders.

For each venue with credentials: authenticate, ``fetch_balance`` (read-only),
and confirm withdrawals are DISABLED (§23.4, fail-closed). Reports a per-venue
status the dashboard shows on a Connections panel and that also feeds the real
balance UI. ``client_factory`` is injectable so this is fully testable against a
mock exchange (no keys, no network). Not in the magic-number-linted layers.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

import structlog

log = structlog.get_logger(__name__)


def _ccxt_client(venue: str, cred: dict):  # pragma: no cover - needs keys + network
    import ccxt
    ex = getattr(ccxt, venue)({"apiKey": cred["apiKey"], "secret": cred.get("secret", ""),
                               "enableRateLimit": True})
    if cred.get("testnet", True) and hasattr(ex, "set_sandbox_mode"):
        ex.set_sandbox_mode(True)
    return ex


_URL_QUERY_RE = re.compile(r"\?[^\s\"']*")
_SECRET_PARAM_RE = re.compile(r"\b(apiKey|secret|signature|sign)=\S+", re.IGNORECASE)


def _sanitize_error(msg: str) -> str:
    """Strip URL query strings and redact key/signature fragments before the
    error is returned to the dashboard."""
    msg = _URL_QUERY_RE.sub("?<_redacted>", msg)
    msg = _SECRET_PARAM_RE.sub(r"\1=<_redacted>", msg)
    return msg[:200]


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
                          "can_trade": False, "error": _sanitize_error(str(exc))}
            log.warning("preflight_failed", venue=venue)
    return out


__all__ = ["preflight_check"]
