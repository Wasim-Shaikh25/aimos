"""Live multi-venue executor wiring — fail-closed, no real keys (§23.8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from aimos.core.config import load_params
from aimos.core.schemas import Action, OrderResult, TradePlan
from aimos.execution.broker.live_router import MultiVenueLiveRouter
from aimos.runtime.golive import GATES, GoLiveLadder
from aimos.runtime.serve import _build_live_router, _maybe_arb


class FakeLiveBroker:
    """Records placed plans and returns deterministic fills."""

    def __init__(self, exchange_id: str, **kwargs) -> None:
        self.exchange_id = exchange_id
        self.placed: list[TradePlan] = []

    def place(self, plan: TradePlan, total_notional_after: float, open_positions_after: int) -> OrderResult:
        self.placed.append(plan)
        return OrderResult(ok=True, order_id=f"order-{self.exchange_id}", status="open", raw={})


class FailingLiveBroker:
    """Simulates one leg failing to fill."""

    def __init__(self, exchange_id: str, **kwargs) -> None:
        self.exchange_id = exchange_id

    def place(self, plan: TradePlan, *args, **kwargs) -> OrderResult:
        if self.exchange_id == "binance":
            return OrderResult(ok=True, order_id="ok", status="open", raw={})
        return OrderResult(ok=False, status="rejected", error="insufficient margin", raw={})


@dataclass
class FakeDecision:
    plan: TradePlan


def _complete_ladder(tmp_path: Path) -> GoLiveLadder:
    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    for gid, *_ in GATES:
        lad.mark(gid)
    return lad


def test_build_live_router_none_by_default(tmp_path):
    params = load_params()
    lad = _complete_ladder(tmp_path)
    router = _build_live_router(params, lad, ["binance", "kraken"])
    assert router is None  # multi_venue_live is false by default


def test_build_live_router_none_when_ladder_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr("aimos.runtime.serve.LiveBroker", FakeLiveBroker)
    params = load_params()
    params.features.multi_venue_live = True
    params.mode = "live"
    params.mandate.enabled = True
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(yaml.safe_dump({"venues": {"binance": {"apiKey": "x"}, "kraken": {"apiKey": "y"}}}), encoding="utf-8")
    params.secrets["file"] = str(secrets_path)
    incomplete = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    assert _build_live_router(params, incomplete, ["binance", "kraken"]) is None


def test_build_live_router_none_without_credentials(tmp_path):
    params = load_params()
    params.features.multi_venue_live = True
    params.mode = "live"
    params.mandate.enabled = True
    lad = _complete_ladder(tmp_path)
    assert _build_live_router(params, lad, ["binance", "kraken"]) is None


def test_build_live_router_creates_brokers_when_gates_open(tmp_path, monkeypatch):
    monkeypatch.setattr("aimos.runtime.serve.LiveBroker", FakeLiveBroker)
    params = load_params()
    params.features.multi_venue_live = True
    params.mode = "live"
    params.mandate.enabled = True
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(yaml.safe_dump({
        "venues": {
            "binance": {"apiKey": "a", "secret": "b"},
            "kraken": {"apiKey": "c", "secret": "d"},
        }
    }), encoding="utf-8")
    params.secrets["file"] = str(secrets_path)
    lad = _complete_ladder(tmp_path)
    router = _build_live_router(params, lad, ["binance", "kraken"])
    assert router is not None
    assert isinstance(router, MultiVenueLiveRouter)
    assert set(router.brokers) == {"binance", "kraken"}


def test_build_live_router_skips_venues_without_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("aimos.runtime.serve.LiveBroker", FakeLiveBroker)
    params = load_params()
    params.features.multi_venue_live = True
    params.mode = "live"
    params.mandate.enabled = True
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(yaml.safe_dump({
        "venues": {"binance": {"apiKey": "a"}}  # only one venue
    }), encoding="utf-8")
    params.secrets["file"] = str(secrets_path)
    lad = _complete_ladder(tmp_path)
    assert _build_live_router(params, lad, ["binance", "kraken"]) is None


def test_maybe_arb_routes_to_live_router_when_present():
    class NoCallSim:
        trades = []

        def execute_arb(self, *args, **kwargs):
            raise AssertionError("sim should not be used when live router is present")

    broker_a = FakeLiveBroker("binance")
    broker_b = FakeLiveBroker("kraken")
    router = MultiVenueLiveRouter({"binance": broker_a, "kraken": broker_b})
    plan = TradePlan(
        plugin="CrossExchangeArb", symbol="BTC/USDT", action=Action.LONG,
        entry=100.0, stop_loss=99.0, take_profit=101.0, expected_rr=1.0,
        expected_hold_minutes=1, expected_costs_bps=0.0, confidence=1.0,
        size_quote=500.0,
        meta={"cross_venue": True, "buy_venue": "binance", "sell_venue": "kraken"},
    )
    holder = {"chosen": {}}
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    _maybe_arb(NoCallSim(), FakeDecision(plan), "BTC", {"binance": 100.0, "kraken": 100.6},
               now, {"starting_equity_usdt": 10000.0}, holder, live_router=router)
    assert len(broker_a.placed) == 1
    assert len(broker_b.placed) == 1
    assert holder["chosen"]["CrossExchangeArb"] == 1


def test_maybe_arb_falls_back_to_sim_when_no_live_router():
    class Sim:
        called = False
        trades = []

        def execute_arb(self, *args, **kwargs):
            Sim.called = True

    plan = TradePlan(
        plugin="CrossExchangeArb", symbol="BTC/USDT", action=Action.LONG,
        entry=100.0, stop_loss=99.0, take_profit=101.0, expected_rr=1.0,
        expected_hold_minutes=1, expected_costs_bps=0.0, confidence=1.0,
        size_quote=500.0,
        meta={"cross_venue": True, "buy_venue": "binance", "sell_venue": "kraken"},
    )
    holder = {"chosen": {}}
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    _maybe_arb(Sim(), FakeDecision(plan), "BTC", {"binance": 100.0, "kraken": 100.6},
               now, {"starting_equity_usdt": 10000.0}, holder)
    assert Sim.called


def test_live_router_flags_needs_unwind_when_one_leg_fails():
    plan = TradePlan(
        plugin="CrossExchangeArb", symbol="BTC/USDT", action=Action.LONG,
        entry=100.0, stop_loss=99.0, take_profit=101.0, expected_rr=1.0,
        expected_hold_minutes=1, expected_costs_bps=0.0, confidence=1.0,
        size_quote=500.0,
        meta={"cross_venue": True, "buy_venue": "binance", "sell_venue": "kraken"},
    )
    router = MultiVenueLiveRouter({
        "binance": FailingLiveBroker("binance"),
        "kraken": FailingLiveBroker("kraken"),
    })
    res = router.execute_arb(
        base_symbol="BTC/USDT", buy_venue="binance", sell_venue="kraken",
        notional_usd=500.0, buy_price=100.0, sell_price=100.6,
        total_notional_after=500.0, positions_after=1,
    )
    assert res.buy.ok is True
    assert res.sell.ok is False
    assert res.both_filled is False
    assert res.needs_unwind is True
