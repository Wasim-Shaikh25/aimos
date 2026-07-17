"""Phase D: secret loading, read-only preflight self-check, gated live arb router.

All tested against a mock exchange — no keys, no network. Verifies the live path
exists and is safe (mandate + withdrawal gated), while staying off by default.
"""

from __future__ import annotations

from aimos.account.preflight import preflight_check
from aimos.account.secrets import load_secrets
from aimos.execution.broker.live import LiveBroker, MandateGate
from aimos.execution.broker.live_router import MultiVenueLiveRouter


# -- secrets -----------------------------------------------------------------


def test_secrets_file_takes_precedence_over_env(tmp_path, monkeypatch):
    f = tmp_path / "secrets.yaml"
    f.write_text("venues:\n  binance:\n    apiKey: FILEKEY\n    secret: s\n", encoding="utf-8")
    monkeypatch.setenv("AIMOS_KEY_BINANCE", "ENVKEY")
    monkeypatch.setenv("AIMOS_SECRET_BINANCE", "s2")
    monkeypatch.setenv("AIMOS_KEY_KRAKEN", "KENV")
    monkeypatch.setenv("AIMOS_SECRET_KRAKEN", "ks")
    creds = load_secrets(str(f), venues=["binance", "kraken", "coinbase"])
    assert creds["binance"]["apiKey"] == "FILEKEY"    # file wins
    assert creds["kraken"]["apiKey"] == "KENV"         # env fallback
    assert "coinbase" not in creds                      # no creds → absent


def test_secrets_absent_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("AIMOS_SECRETS_FILE", raising=False)
    assert load_secrets("", venues=["binance"]) == {}


# -- preflight self-check ----------------------------------------------------


class _MockExchange:
    def __init__(self, usdt=1234.0, fail=False):
        self._usdt, self._fail = usdt, fail

    def fetch_balance(self):
        if self._fail:
            raise RuntimeError("auth failed")
        return {"USDT": {"free": self._usdt, "used": 0.0, "total": self._usdt}}


def test_preflight_reports_connected_and_withdrawal_disabled():
    creds = {"binance": {"apiKey": "k", "secret": "s", "withdraw": False},
             "kraken": {"apiKey": "k", "secret": "s", "withdraw": True}}  # can withdraw!
    res = preflight_check(
        ["binance", "kraken", "coinbase"], creds,
        client_factory=lambda v, c: _MockExchange(usdt=500.0))
    assert res["binance"]["connected"] and res["binance"]["can_trade"]
    assert res["binance"]["usdt_free"] == 500.0
    # withdrawal-enabled key: connected but NOT allowed to trade (fail-closed §23.4)
    assert res["kraken"]["connected"] and res["kraken"]["can_trade"] is False
    # no creds → configured False, never connected
    assert res["coinbase"]["configured"] is False


def test_preflight_reports_auth_failure_without_crashing():
    creds = {"binance": {"apiKey": "bad", "secret": "s"}}
    res = preflight_check(["binance"], creds,
                          client_factory=lambda v, c: _MockExchange(fail=True))
    assert res["binance"]["connected"] is False and res["binance"]["error"]


# -- gated live arb router (mock ccxt) ---------------------------------------


class _MockCcxt:
    def __init__(self):
        self.orders = []

    def create_order(self, symbol, typ, side, amount, price, params=None):
        self.orders.append((symbol, side, amount, price))
        return {"id": f"{side}-1", "filled": amount, "average": price}


def _live_broker(mandate_enabled=True):
    cfg = {"enabled": mandate_enabled, "max_total_notional_usdt": 1e9,
           "max_positions": 10, "allowed_quotes": ["USDT"]}
    return LiveBroker("binance", MandateGate(cfg), {"withdraw": False}, exchange=_MockCcxt())


def test_live_router_places_both_legs():
    router = MultiVenueLiveRouter({"binance": _live_broker(), "kraken": _live_broker()})
    r = router.execute_arb("BTC/USDT", "binance", "kraken", 1_000.0, 100.0, 100.6, 1_000.0, 1)
    assert r.both_filled and not r.needs_unwind
    assert r.buy.ok and r.sell.ok


def test_live_router_refuses_when_mandate_disabled():
    # mandate off → both legs rejected (fail-closed), nothing placed
    router = MultiVenueLiveRouter({"binance": _live_broker(mandate_enabled=False),
                                   "kraken": _live_broker(mandate_enabled=False)})
    r = router.execute_arb("BTC/USDT", "binance", "kraken", 1_000.0, 100.0, 100.6, 1_000.0, 1)
    assert not r.both_filled
    assert not r.buy.ok and not r.sell.ok
