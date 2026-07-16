"""On-chain data providers (§5.9).

A ``OnchainProvider`` returns per-asset on-chain series (active addresses,
stablecoin exchange inflow). ``FreeApiOnchainProvider`` fetches from free public
endpoints (lazy httpx, no keys); ``StaticOnchainProvider`` serves fixtures so the
on-chain engine is testable offline. Not in the linted layers.
"""

from __future__ import annotations

from typing import Optional, Protocol


class OnchainProvider(Protocol):
    def get(self, base: str) -> Optional[dict]:
        """Return {"active_addresses": [...], "stablecoin_inflow": [...]} or None."""
        ...


class StaticOnchainProvider:
    """Fixture provider (offline/tests)."""

    def __init__(self, data: dict[str, dict]) -> None:
        self._data = data

    def get(self, base: str) -> Optional[dict]:
        return self._data.get(base.upper())


class FreeApiOnchainProvider:
    """Fetches free on-chain metrics (lazy httpx; best-effort, no keys).

    Endpoints are pluggable; a failed fetch returns None so the engine degrades
    gracefully (§10.1). Kept minimal — the point is a real, swappable adapter.
    """

    def __init__(self, endpoints: Optional[dict[str, str]] = None) -> None:
        self.endpoints = endpoints or {}

    def get(self, base: str) -> Optional[dict]:  # pragma: no cover - network
        url = self.endpoints.get(base.upper())
        if not url:
            return None
        try:
            import httpx
            r = httpx.get(url, timeout=10.0)
            payload = r.json()
            return {
                "active_addresses": payload.get("active_addresses", []),
                "stablecoin_inflow": payload.get("stablecoin_inflow", []),
            }
        except Exception:
            return None


__all__ = ["FreeApiOnchainProvider", "OnchainProvider", "StaticOnchainProvider"]
