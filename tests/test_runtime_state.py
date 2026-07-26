"""Runtime state persistence: save/load equity, broker, and multi-venue balances."""

from __future__ import annotations

from aimos.backtest.costs import CostModel
from aimos.data.candles import OHLCV_COLUMNS
from aimos.execution.broker.multivenue import MultiVenueSim
from aimos.execution.broker.paper import PaperBroker
from aimos.runtime.state_store import RuntimeStateStore, build_snapshot


def _make_broker():
    return PaperBroker(
        10000.0,
        CostModel(taker_bps=5.0, maker_bps=2.0, slip_base_bps=1.0, slip_k=0.5),
        venue="binance",
    )


def test_state_store_roundtrip(tmp_path):
    store = RuntimeStateStore("local", state_dir=tmp_path / "tenant_local_state")
    broker = _make_broker()
    broker._cash = 9000.0
    broker._realized = 100.0
    sim = MultiVenueSim(["binance", "kraken"], 10000.0, 5.0)
    sim.balances = {"binance": {"USDT": 6000.0}, "kraken": {"USDT": 4000.0}}
    holder = {"equity": [10000.0, 9900.0, 10100.0], "features": {"scalp_enabled": True}, "monitor": {}}

    snapshot = build_snapshot(holder, broker, sim, None)
    store.save(snapshot)
    loaded = store.load()

    assert loaded["equity"] == [10000.0, 9900.0, 10100.0]
    assert loaded["broker"]["cash"] == 9000.0
    assert loaded["sim"]["balances"]["binance"]["USDT"] == 6000.0
    assert loaded["features"]["scalp_enabled"] is True


def test_state_store_noop_for_memory():
    store = RuntimeStateStore("local", state_dir=None)
    assert store.load() == {}
    store.save({"x": 1})  # should not raise
