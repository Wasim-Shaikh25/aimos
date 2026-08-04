"""On-chain data providers (§5.9).

A ``OnchainProvider`` returns per-asset on-chain series (active addresses,
stablecoin exchange inflow). ``FreeApiOnchainProvider`` fetches from free public
endpoints (lazy httpx, no keys); ``StaticOnchainProvider`` serves fixtures so the
on-chain engine is testable offline. Not in the linted layers.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol


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


class CoinMetricsCommunityProvider:
    """Direct connector to the Coin Metrics Community API (§5.9, REQ-16).

    Fetches ``AdrActCnt`` for the requested base asset and ``FlowInAllNtv`` for a
    configurable stablecoin asset. No API key is required for the community tier;
    a paid ``api_key`` can be supplied for higher rate limits. A failed or empty
    fetch degrades to ``None`` so the on-chain engine remains dormant.
    """

    def __init__(
        self,
        base_url: str = "https://community-api.coinmetrics.io/v4",
        api_key: str = "",
        active_addresses_metric: str = "AdrActCnt",
        stablecoin_inflow_metric: str = "FlowInAllNtv",
        stablecoin_asset: str = "usdt",
        page_size: int = 100,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.active_addresses_metric = active_addresses_metric
        self.stablecoin_inflow_metric = stablecoin_inflow_metric
        self.stablecoin_asset = stablecoin_asset
        self.page_size = page_size
        self.timeout = timeout

    def _fetch_series(self, asset: str, metric: str) -> list[float]:
        """Fetch a single Coin Metrics time-series and return a list of float values."""
        import httpx

        params: dict[str, Any] = {
            "assets": asset.lower(),
            "metrics": metric,
            "frequency": "1d",
            "page_size": self.page_size,
            "format": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.base_url}/timeseries/asset-metrics"
        r = httpx.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        out: list[float] = []
        for row in payload.get("data", []):
            raw = row.get(metric)
            if raw is None:
                continue
            try:
                out.append(float(raw))
            except (TypeError, ValueError):
                continue
        return out

    def get(self, base: str) -> Optional[dict]:
        """Return active-address and stablecoin-inflow series for ``base``."""
        base_upper = base.upper()
        try:
            active = self._fetch_series(base_upper, self.active_addresses_metric)
        except Exception:
            return None
        if not active:
            return None
        result: dict[str, list[float]] = {"active_addresses": active}
        # Stablecoin inflow is a market-wide reading, not pair-specific.
        try:
            inflow = self._fetch_series(self.stablecoin_asset.upper(), self.stablecoin_inflow_metric)
            if inflow:
                result["stablecoin_inflow"] = inflow
        except Exception:
            pass
        return result


__all__ = [
    "CoinMetricsCommunityProvider",
    "FreeApiOnchainProvider",
    "OnchainProvider",
    "StaticOnchainProvider",
]
