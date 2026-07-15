"""Universe discovery + filter tests (§16.1 A-B — card P15-T1 DoD)."""

from __future__ import annotations

import pytest

from aimos.universe.discovery import MarketInfo, MarketQuality, discover
from aimos.universe.filters import filter_market, is_leveraged_token

ALLOWED = {"USDT", "USDC", "FDUSD", "DAI"}
EXCLUDE_BASES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "BUSD", "EUR", "GBP", "TRY", "BRL"}

FILTER_KW = dict(
    allowed_quotes=ALLOWED,
    exclude_bases=EXCLUDE_BASES,
    exclude_leveraged_tokens=True,
    min_24h_volume_usd=2_000_000,
    min_book_depth_usd_0p5pct=50_000,
    max_spread_bps=15,
    min_listing_age_days=30,
    max_atr_pct_per_day=15,
)


def _market(symbol, base, quote, active=True):
    return MarketInfo(
        exchange="binance", symbol=symbol, base=base, quote=quote, type="spot",
        active=active, min_notional=5.0, lot_step=0.001, taker_bps=7.5, maker_bps=2.0,
    )


def _good_quality():
    return MarketQuality(
        volume_24h_usd=5_000_000, book_depth_usd_0p5pct=100_000,
        spread_bps=5, listing_age_days=365, atr_pct_per_day=4.0,
    )


def test_discover_maps_ccxt_markets():
    markets = {
        "SOL/USDT": {
            "symbol": "SOL/USDT", "base": "SOL", "quote": "USDT", "type": "spot",
            "active": True, "limits": {"cost": {"min": 5.0}},
            "precision": {"amount": 0.001}, "taker": 0.00075, "maker": 0.0002,
        }
    }
    infos = discover("binance", markets)
    assert infos[0].taker_bps == pytest.approx(7.5)
    assert infos[0].base == "SOL"


def test_eur_pair_rejected():
    r = filter_market(_market("BTC/EUR", "BTC", "EUR"), _good_quality(), **FILTER_KW)
    assert not r.passed and r.reason == "quote"


def test_crypto_crypto_pair_rejected():
    # ETH/BTC — quote BTC not allowed
    r = filter_market(_market("ETH/BTC", "ETH", "BTC"), _good_quality(), **FILTER_KW)
    assert not r.passed and r.reason == "quote"


def test_stable_base_rejected():
    # USDC/USDT — stable/stable
    r = filter_market(_market("USDC/USDT", "USDC", "USDT"), _good_quality(), **FILTER_KW)
    assert not r.passed and r.reason == "stable_base"


@pytest.mark.parametrize("base", ["BTC3L", "ETH3S", "BTCUP", "ETHDOWN", "SOLBULL", "XRPBEAR"])
def test_leveraged_tokens_rejected(base):
    assert is_leveraged_token(base)
    r = filter_market(_market(f"{base}/USDT", base, "USDT"), _good_quality(), **FILTER_KW)
    assert not r.passed and r.reason == "leveraged"


def test_normal_asset_not_leveraged():
    assert not is_leveraged_token("SOL")
    assert not is_leveraged_token("BTC")


def test_quality_filters():
    m = _market("SOL/USDT", "SOL", "USDT")
    low_vol = MarketQuality(volume_24h_usd=1_000, book_depth_usd_0p5pct=100_000,
                            spread_bps=5, listing_age_days=365, atr_pct_per_day=4.0)
    assert filter_market(m, low_vol, **FILTER_KW).reason == "volume"

    wide = MarketQuality(volume_24h_usd=5_000_000, book_depth_usd_0p5pct=100_000,
                         spread_bps=40, listing_age_days=365, atr_pct_per_day=4.0)
    assert filter_market(m, wide, **FILTER_KW).reason == "spread"

    fresh = MarketQuality(volume_24h_usd=5_000_000, book_depth_usd_0p5pct=100_000,
                          spread_bps=5, listing_age_days=5, atr_pct_per_day=4.0)
    assert filter_market(m, fresh, **FILTER_KW).reason == "age"

    wild = MarketQuality(volume_24h_usd=5_000_000, book_depth_usd_0p5pct=100_000,
                         spread_bps=5, listing_age_days=365, atr_pct_per_day=25.0)
    assert filter_market(m, wild, **FILTER_KW).reason == "volatility"


def test_good_market_passes():
    r = filter_market(_market("SOL/USDT", "SOL", "USDT"), _good_quality(), **FILTER_KW)
    assert r.passed and r.reason == ""
