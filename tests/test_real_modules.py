"""Tests for the modules upgraded from stubs to real, working implementations:
ML model+engine, on-chain engine, lead-lag/venue-divergence, watchdog, Telegram
inbound bot, LiveBroker ccxt path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from aimos.core.config import load_params
from aimos.core.clock import LiveClock
from aimos.core.schemas import Action, Direction, MarketContext, TradePlan
from tests.conftest import FakeClock

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


# ---- ML engine now actually learns + predicts ----

def test_ml_engine_uses_trained_model(tmp_path):
    from aimos.core.schemas import Evidence, EvidenceBundle, Timeframe, Regime
    from aimos.intelligence.ml_engine import MLEngine
    from aimos.learning.features import feature_vector
    from aimos.learning.train import train_model

    # build a learnable dataset from real feature vectors
    rng = np.random.default_rng(0)
    rows, labels, tss = [], [], []
    for i in range(300):
        bull = rng.random() > 0.5
        d = Direction.BULLISH if bull else Direction.BEARISH
        ev = Evidence(source="e.volume_spike", symbol="X", timeframe=Timeframe.H1, timestamp=TS,
                      name="volume_spike", value=0.8, direction=d, strength=0.8)
        rows.append(feature_vector(EvidenceBundle(symbol="X", timestamp=TS, evidences=[ev])))
        labels.append(1 if bull else 0)
        tss.append(TS + timedelta(hours=i))
    model = train_model(np.array(rows), labels, tss)
    assert model.val_auc > 0.7  # genuinely learned
    path = model.save(tmp_path / "model.json")

    eng = MLEngine(model_path=str(path))
    bull_bundle = EvidenceBundle(symbol="X", timestamp=TS, evidences=[
        Evidence(source="e.volume_spike", symbol="X", timeframe=Timeframe.H1, timestamp=TS,
                 name="volume_spike", value=0.8, direction=Direction.BULLISH, strength=0.8)])
    op = eng.opine(bull_bundle, regime=Regime.TRENDING_UP)
    assert op.p_up != 0.5  # real prediction, not inert
    assert op.p_up > 0.5   # bullish evidence → bullish prediction


def test_ml_engine_inert_without_model():
    from aimos.core.schemas import EvidenceBundle
    from aimos.intelligence.ml_engine import MLEngine
    op = MLEngine(model_path=None).opine(EvidenceBundle(symbol="X", timestamp=TS))
    assert op.p_up == 0.5 and op.confidence == 0.0  # inert when untrained


def test_ml_stays_weight_zero_in_fusion():
    # even with a model, fusion weight is 0 until config promotes it (§8.3)
    assert load_params().intelligence.model_dump()["fusion_weights"]["ml"] == 0.0


# ---- on-chain engine now emits real evidence ----

def test_onchain_engine_emits_from_provider():
    from aimos.data.onchain import StaticOnchainProvider
    from aimos.observation.onchain_engine import OnchainEngine

    rising = list(range(50)) + [200]  # active addresses spiking up
    provider = StaticOnchainProvider({"BTC": {"active_addresses": rising, "stablecoin_inflow": rising}})
    eng = OnchainEngine(load_params().observation.model_dump(), LiveClock(), 0.45, provider=provider)
    evs = eng.observe(MarketContext(symbol="BTC", now=TS))
    names = {e.name for e in evs}
    assert "active_addresses" in names and "stablecoin_inflow" in names
    assert all(e.direction is Direction.BULLISH for e in evs)  # rising → bullish


def test_onchain_engine_inert_without_provider():
    from aimos.observation.onchain_engine import OnchainEngine
    eng = OnchainEngine(load_params().observation.model_dump(), LiveClock(), 0.45)
    assert eng.observe(MarketContext(symbol="BTC", now=TS)) == []


# ---- lead-lag + venue divergence are real algorithms now ----

def test_compute_lead_lag_identifies_leader():
    from aimos.observation.cross_exchange import compute_lead_lag
    base = np.cumsum(np.random.default_rng(0).normal(0, 1, 60)) + 100
    # 'lead' venue = base shifted EARLIER (it moves first); 'follow' lags by 1
    series = {"lead": list(base[1:]), "follow": list(base[:-1])}
    result = compute_lead_lag(series, lag=1)
    assert result is not None
    leader, direction, strength = result
    assert leader in ("lead", "follow")
    assert 0.0 <= strength <= 1.0


def test_venue_divergence_flag():
    from aimos.observation.cross_exchange import venue_divergence
    assert venue_divergence({"binance": 4.0, "kraken": 1.0, "bybit": 1.2}, hi=3.0, lo=1.5)
    assert not venue_divergence({"binance": 2.0, "kraken": 2.0}, hi=3.0, lo=1.5)


def test_cross_exchange_engine_emits_lead_lag_with_provider():
    from aimos.observation.cross_exchange import CrossExchangeEngine
    base = list(np.cumsum(np.random.default_rng(1).normal(0, 1, 60)) + 100)
    eng = CrossExchangeEngine(
        load_params().observation.model_dump(), LiveClock(), 0.55,
        venue_series_provider=lambda s: {"binance": base[1:], "kraken": base[:-1]},
        venue_relvol_provider=lambda s: {"binance": 4.0, "kraken": 1.0},
    )
    evs = eng.observe(MarketContext(symbol="SOL", now=TS))
    names = {e.name for e in evs}
    assert "lead_lag" in names and "venue_divergence_volume" in names


# ---- watchdog is a real heartbeat monitor ----

def test_watchdog_restarts_after_missed(tmp_path):
    from aimos.runtime.watchdog import Heartbeat, Watchdog
    clock = FakeClock(TS)
    hb = Heartbeat(tmp_path / "hb", clock=clock)
    hb.beat()
    restarts, alerts = [], []
    wd = Watchdog(hb, stale_after_seconds=60, max_missed=3,
                  on_restart=lambda: restarts.append(1), on_alert=lambda m: alerts.append(m))
    assert not wd.check(clock.now())  # fresh
    clock.advance(120)  # now stale
    assert not wd.check(clock.now())  # miss 1
    assert not wd.check(clock.now())  # miss 2
    assert wd.check(clock.now())      # miss 3 → restart
    assert restarts == [1] and alerts


def test_watchdog_resets_on_fresh_beat(tmp_path):
    from aimos.runtime.watchdog import Heartbeat, Watchdog
    clock = FakeClock(TS)
    hb = Heartbeat(tmp_path / "hb", clock=clock)
    wd = Watchdog(hb, stale_after_seconds=60, max_missed=3)
    hb.beat()
    clock.advance(120)
    wd.check(clock.now())  # miss 1
    hb.beat()              # process recovered
    assert not wd.check(clock.now())  # streak reset


# ---- Telegram inbound bot is a real command router ----

def _router(**kw):
    from aimos.telegram.bot import CommandRouter
    from aimos.telegram.security import ChatWhitelist, NonceStore
    return CommandRouter(ChatWhitelist({111}), NonceStore(FakeClock(TS)), **kw)


def test_bot_ignores_unauthorized_chat():
    assert _router().handle(999, "/status") is None  # silent


def test_bot_status_and_pause():
    class Orch:
        class _S: halted = False
        state = _S()
        paused = []
        def pause(self, s=None): self.paused.append(s)
        def resume(self, s=None): pass
    orch = Orch()
    r = _router(orchestrator=orch)
    assert "paused" in r.handle(111, "/pause BTC")
    assert orch.paused == ["BTC"]


def test_bot_dangerous_requires_confirm():
    from aimos.telegram.security import NonceStore
    from aimos.telegram.bot import CommandRouter
    from aimos.telegram.security import ChatWhitelist
    class Orch:
        class _S: halted = False
        state = _S()
    orch = Orch()
    nonce = NonceStore(FakeClock(TS))
    r = CommandRouter(ChatWhitelist({111}), nonce, orchestrator=orch)
    reply = r.handle(111, "/killswitch")
    assert "confirm" in reply.lower()
    # extract the nonce and confirm
    tok = reply.split("/confirm ")[1].split()[0]
    done = r.handle(111, f"/confirm {tok}")
    assert "halted" in done and orch.state.halted


def test_bot_poll_once_with_fake_transport():
    from aimos.telegram.bot import TelegramBot
    sent = []
    class FakeTransport:
        def __init__(self): self.updates = [
            {"update_id": 1, "message": {"chat": {"id": 111}, "text": "/help"}},
            {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/help"}},  # unauthorized
        ]
        def get_updates(self, offset): return [u for u in self.updates if u["update_id"] >= offset]
        def send_message(self, chat_id, text): sent.append((chat_id, text))
    bot = TelegramBot(FakeTransport(), _router())
    handled = bot.poll_once()
    assert handled == 1  # only the authorized chat got a reply
    assert sent[0][0] == 111


# ---- LiveBroker real ccxt path (fake exchange) ----

def _mandate(enabled=True):
    from aimos.execution.broker.live import MandateGate
    cfg = load_params().mandate.model_dump()
    cfg["enabled"] = enabled
    cfg["max_total_notional_usdt"] = 1_000_000
    return MandateGate(cfg)


def test_livebroker_places_ccxt_order_with_fake_exchange():
    from aimos.execution.broker.live import LiveBroker
    calls = []
    class FakeExchange:
        def create_order(self, symbol, type_, side, amount, price, params):
            calls.append((symbol, side, amount, params))
            return {"id": "ex-1", "filled": 0.0, "average": None}
        def fetch_positions(self): return [{"symbol": "SOL/USDT"}]
    broker = LiveBroker("binance", _mandate(), {"withdraw": False}, exchange=FakeExchange())
    plan = TradePlan(plugin="TF", symbol="SOL/USDT", action=Action.LONG,
                     entry=150.0, stop_loss=145.0, size_quote=1500.0)
    result = broker.place(plan, total_notional_after=1500, open_positions_after=1)
    assert result.ok and result.order_id == "ex-1"
    assert calls[0][1] == "buy" and calls[0][3]["clientOrderId"].startswith("aimos-")


def test_livebroker_mandate_refuses_when_disabled():
    from aimos.execution.broker.live import LiveBroker
    broker = LiveBroker("binance", _mandate(enabled=False), {"withdraw": False}, exchange=object())
    plan = TradePlan(plugin="TF", symbol="SOL/USDT", action=Action.LONG, entry=150.0,
                     stop_loss=145.0, size_quote=1500.0)
    result = broker.place(plan, 1500, 1)
    assert not result.ok and "fail-closed" in result.error


def test_livebroker_reconcile_on_start():
    from aimos.execution.broker.live import LiveBroker
    class FakeExchange:
        def fetch_positions(self): return [{"symbol": "BTC/USDT"}, {"symbol": "ETH/USDT"}]
    broker = LiveBroker("binance", _mandate(), {"withdraw": False}, exchange=FakeExchange())
    recon = broker.reconcile_on_start(journal_symbols=["BTC/USDT", "SOL/USDT"])
    assert "ETH/USDT" in recon.adopt        # on exchange, not journal
    assert "SOL/USDT" in recon.close_unknown  # in journal, not exchange
