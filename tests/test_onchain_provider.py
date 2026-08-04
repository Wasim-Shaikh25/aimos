"""Tests for the on-chain data providers and engine wiring (§5.9, REQ-16)."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from aimos.core.clock import LiveClock
from aimos.core.config import load_params
from aimos.data.onchain import (
    CoinMetricsCommunityProvider,
    FreeApiOnchainProvider,
    StaticOnchainProvider,
)
from aimos.observation.onchain_engine import OnchainEngine
from aimos.observation.runner import _build_onchain_provider, build_engines


@pytest.fixture
def params():
    return load_params()


def _params_with_onchain(params, enabled: bool, provider: str):
    raw = deepcopy(params.model_dump())
    raw["observation"]["onchain"]["enabled"] = enabled
    raw["observation"]["onchain"]["provider"] = provider
    from aimos.core.config import Params
    return Params.model_validate(raw)


def test_static_onchain_provider_returns_fixture():
    data = {"BTC": {"active_addresses": [1.0, 2.0, 3.0]}}
    p = StaticOnchainProvider(data)
    assert p.get("btc") == {"active_addresses": [1.0, 2.0, 3.0]}
    assert p.get("eth") is None


def test_freeapi_onchain_provider_missing_endpoint():
    p = FreeApiOnchainProvider()
    assert p.get("btc") is None


def test_coinmetrics_provider_parses_series():
    p = CoinMetricsCommunityProvider()
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "data": [
            {"time": "2026-07-30T00:00:00Z", "AdrActCnt": "100"},
            {"time": "2026-07-31T00:00:00Z", "AdrActCnt": "200"},
            {"time": "2026-08-01T00:00:00Z", "AdrActCnt": "abc"},
        ],
    }

    call_count = 0
    def _fake_get(url, params=None, timeout=None):
        nonlocal call_count
        call_count += 1
        metric = params.get("metrics") if params else ""
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {"time": "2026-07-30T00:00:00Z", metric: "100"},
                {"time": "2026-07-31T00:00:00Z", metric: "200"},
                {"time": "2026-08-01T00:00:00Z", metric: "abc"},
            ],
        }
        return response

    with patch("httpx.get", _fake_get):
        result = p.get("btc")

    assert result is not None
    assert result["active_addresses"] == [100.0, 200.0]
    assert result["stablecoin_inflow"] == [100.0, 200.0]
    assert call_count == 2  # active addresses + stablecoin inflow


def test_coinmetrics_provider_returns_none_on_failure():
    p = CoinMetricsCommunityProvider()
    with patch("httpx.get", side_effect=RuntimeError("network down")):
        assert p.get("btc") is None


def test_build_onchain_provider_disabled():
    assert _build_onchain_provider({"enabled": False, "provider": "coinmetrics"}) is None


def test_build_onchain_provider_unknown():
    assert _build_onchain_provider({"enabled": True, "provider": "nope"}) is None


def test_build_onchain_provider_coinmetrics():
    provider = _build_onchain_provider({"enabled": True, "provider": "coinmetrics", "api_key": "abc"})
    assert isinstance(provider, CoinMetricsCommunityProvider)
    assert provider.api_key == "abc"


def test_build_engines_passes_provider_to_onchain_when_enabled(params):
    p = _params_with_onchain(params, True, "coinmetrics")
    engines = build_engines(p, LiveClock())
    onchain = [e for e in engines if isinstance(e, OnchainEngine)]
    assert len(onchain) == 1
    assert isinstance(onchain[0].provider, CoinMetricsCommunityProvider)


def test_build_engines_no_provider_when_onchain_disabled(params):
    engines = build_engines(params, LiveClock())
    onchain = [e for e in engines if isinstance(e, OnchainEngine)]
    assert len(onchain) == 1
    assert onchain[0].provider is None
