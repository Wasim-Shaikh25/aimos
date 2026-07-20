"""Integration validation harness — tested against a mock exchange (no keys/network)."""

from __future__ import annotations

from aimos.core.schemas import OrderResult
from aimos.execution.broker.live import LiveBroker, MandateGate
from aimos.runtime.golive import GoLiveLadder
from aimos.runtime.validate import validate_integration


class _MockClient:
    def fetch_balance(self):
        return {"USDT": {"free": 42.0, "total": 42.0}}


class _MockCcxt:
    def create_order(self, *a, **k):
        return {"id": "ok-1", "filled": a[3] if len(a) > 3 else 0.0, "average": 1.0}
    def cancel_all_orders(self, symbol):
        return True
    def fetch_positions(self):
        return []


def _broker():
    cfg = {"enabled": True, "max_total_notional_usdt": 1e9, "max_positions": 10,
           "allowed_quotes": ["USDT"]}
    return LiveBroker("binance", MandateGate(cfg), {"withdraw": False}, exchange=_MockCcxt())


def test_validate_all_pass_marks_testnet_gate(tmp_path):
    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    rep = validate_integration(
        "binance", {"apiKey": "k", "secret": "s", "withdraw": False}, _broker(), ladder=lad,
        client_factory=lambda v, c: _MockClient())
    assert rep.all_ok
    names = {s["name"] for s in rep.steps}
    assert {"authenticate + fetch balance", "withdrawals disabled (§23.4)",
            "place order", "cancel + reconcile"} <= names
    # all-pass started the testnet clock
    tgate = next(g for g in lad.status()["gates"] if g["id"] == "testnet_1wk")
    assert tgate["progress"] is not None


def test_validate_flags_withdrawal_enabled_key(tmp_path):
    rep = validate_integration(
        "binance", {"apiKey": "k", "secret": "s", "withdraw": True}, _broker(),
        ladder=GoLiveLadder(state_path=str(tmp_path / "gl.json")),
        client_factory=lambda v, c: _MockClient())
    # a withdrawal-enabled key fails the safety step → not all-pass
    assert rep.all_ok is False
    wd = next(s for s in rep.steps if "withdrawals" in s["name"])
    assert wd["ok"] is False
