"""Canonical registry + intersection tests (§16.1 B-C — card P15-T2 DoD)."""

from __future__ import annotations

from aimos.universe.discovery import MarketInfo
from aimos.universe.intersection import build_matrix, common
from aimos.universe.registry import Registry


def _m(exchange, symbol, base, quote):
    return MarketInfo(
        exchange=exchange, symbol=symbol, base=base, quote=quote, type="spot",
        active=True, min_notional=5.0, lot_step=0.001, taker_bps=7.5, maker_bps=2.0,
    )


def _populated() -> Registry:
    reg = Registry(primary_exchange="binance")
    reg.add_all([
        _m("binance", "SOL/USDT", "SOL", "USDT"),
        _m("kraken", "SOL/USDC", "SOL", "USDC"),  # same canonical asset SOL
        _m("binance", "BTC/USDT", "BTC", "USDT"),
        _m("bybit", "BTC/USDT", "BTC", "USDT"),
        _m("kraken", "BTC/USDT", "BTC", "USDT"),
        _m("binance", "PEPE/USDT", "PEPE", "USDT"),  # single-venue
    ])
    return reg


def test_usdt_and_usdc_map_to_same_base():
    reg = _populated()
    assert "SOL" in reg.bases()
    assert set(reg.venues("SOL")) == {"binance", "kraken"}
    # canonical analysis uses the primary-venue market
    assert reg.primary_market("SOL").symbol == "SOL/USDT"
    assert reg.market("SOL", "kraken").symbol == "SOL/USDC"


def test_intersection_common():
    reg = _populated()
    # BTC on 3 venues, SOL on 2, PEPE on 1
    assert common(reg, min_venues=2) == {"SOL", "BTC"}
    assert common(reg, min_venues=3) == {"BTC"}


def test_matrix_shape():
    reg = _populated()
    matrix = build_matrix(reg)
    assert matrix["BTC"] == {"binance": True, "bybit": True, "kraken": True}
    assert matrix["PEPE"] == {"binance": True}


def test_quote_suspension_removes_venue():
    reg = _populated()
    reg.suspend_quote("USDC")  # depeg
    assert reg.is_quote_suspended("USDC")
    # SOL/USDC on kraken disappears; SOL/USDT on binance remains
    assert reg.venues("SOL") == ["binance"]
    assert "SOL" not in common(reg, min_venues=2)


def test_delist_flags_cross_venue_positions():
    reg = _populated()
    result = reg.delist("BTC", "bybit")  # still on binance + kraken
    assert result["cross_venue_flatten"] is True
    assert set(result["remaining_venues"]) == {"binance", "kraken"}
    assert "bybit" not in reg.venues("BTC")


def test_delist_last_venue_no_cross_flatten():
    reg = _populated()
    result = reg.delist("PEPE", "binance")  # was single-venue
    assert result["cross_venue_flatten"] is False
    assert result["remaining_venues"] == []
