"""TimescaleDB time-series store — optional, graceful no-op without a DSN/psycopg."""

from __future__ import annotations

from datetime import datetime, timezone

from aimos.storage.timescale import TimescaleStore


def test_store_is_noop_without_dsn():
    s = TimescaleStore("")
    assert s.enabled is False
    now = datetime.now(timezone.utc)
    # every write is a safe no-op — never raises, even with no backend
    s.write_equity(now, 10_000.0)
    s.write_decision(now, "BTC", "binance", "trending_up", 0.7, "no_trade", "RiskOff")
    s.write_price(now, "BTC", "binance", 30_000.0, 12.5)
    s.write_trade(now, "arb", "BTC", "CrossExchangeArb", "binance→kraken", 4.4)
    s.close()


def test_store_with_dsn_but_no_backend_falls_back(monkeypatch):
    # a DSN is set but psycopg/DB is unavailable → stays a no-op, doesn't crash
    monkeypatch.delenv("AIMOS_TIMESCALE_DSN", raising=False)
    s = TimescaleStore("postgresql://nobody@localhost:1/none")
    assert s.enabled is False
    s.write_equity(datetime.now(timezone.utc), 1.0)  # no raise
