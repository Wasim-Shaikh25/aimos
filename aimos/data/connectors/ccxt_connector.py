"""ccxt-backed connectors (§4, §25.8 typed errors).

ccxt is an optional dependency (``pip install -e '.[data]'``); it is imported
lazily so the contracts/tests do not require it. All REST access in production
must be routed through the rate-limit budgeter (§23.2) — callers pass an
acquired budget; these thin wrappers only translate ccxt shapes.
"""

from __future__ import annotations

from typing import Any


class DataError(Exception):
    """Generic data-connector error (§25.8)."""


class VenueError(DataError):
    """A venue-specific failure (down, rejected, rate-limited) (§25.8)."""


def _load_ccxt() -> Any:
    try:
        import ccxt  # noqa: PLC0415 - lazy optional import
    except ImportError as exc:  # pragma: no cover - env without the data extra
        raise DataError(
            "ccxt is not installed; install with: pip install -e '.[data]'"
        ) from exc
    return ccxt


class CcxtCandleFetcher:
    """Adapts a ccxt exchange to the ``CandleFetcher`` protocol (§4.1)."""

    def __init__(self, exchange_id: str, params: dict[str, Any] | None = None) -> None:
        ccxt = _load_ccxt()
        if not hasattr(ccxt, exchange_id):
            raise VenueError(f"unknown exchange {exchange_id!r}")
        self.exchange_id = exchange_id
        self._ex = getattr(ccxt, exchange_id)(params or {"enableRateLimit": True})

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None, limit: int
    ) -> list[list[float]]:
        try:
            return self._ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as exc:  # pragma: no cover - network path
            raise VenueError(f"{self.exchange_id} fetch_ohlcv failed: {exc}") from exc

    def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        """Public best (bid, ask) for one symbol — for cross-exchange work (§5.11)."""
        try:
            t = self._ex.fetch_ticker(symbol)  # public, no keys
        except Exception as exc:  # pragma: no cover - network path
            raise VenueError(f"{self.exchange_id} fetch_ticker failed: {exc}") from exc
        bid, ask = t.get("bid"), t.get("ask")
        if bid is None or ask is None:  # some venues only give last
            last = t.get("last") or t.get("close")
            if last is None:
                raise VenueError(f"{self.exchange_id} ticker for {symbol} has no book")
            bid = ask = float(last)
        return float(bid), float(ask)


__all__ = ["CcxtCandleFetcher", "DataError", "VenueError"]
