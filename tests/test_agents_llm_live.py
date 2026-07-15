"""Agents + LLM sensor + LiveBroker/mandate + scalp/MM tests
(§18.3, §19, §7.6, §20.4, §17, §21.2 — cards P6-T3/T4/T5/T6/T7)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import Action, Behavior, Direction, Headline, Regime
from tests.conftest import make_exec_ctx, make_mu

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


# ---- agents (P6-T4) ----

def test_a1_proposal_approve_writes_staging_not_config(tmp_path):
    from aimos.agents.analyst import ResearchAnalyst
    from aimos.agents.proposals import ConfigMutationForbidden, ProposalStatus, approve, reject

    prop = ResearchAnalyst().propose_disable_in_regime(
        "Pullback", "ranging", hit_rate=0.31, n_trades=60, proposal_id="p1", hypothesis_id="h1")
    path = approve(prop, tmp_path / "staging")
    assert path.exists() and prop.status is ProposalStatus.APPROVED
    # never writes into config/
    with pytest.raises(ConfigMutationForbidden):
        approve(prop, tmp_path / "config" / "staging")
    # rejection requires a reason
    with pytest.raises(ValueError):
        reject(prop, "")


def test_a2_sentinel_notify_only():
    from aimos.agents.sentinel import RiskSentinel, Severity

    s = RiskSentinel()
    # sentinel has NO mutate/pause/flatten methods (§18.3)
    assert not hasattr(s, "pause") and not hasattr(s, "flatten") and not hasattr(s, "veto")
    d = s.digest(positions=[1, 2, 3], heat_pct=1.9, correlations={"BTC-ETH": 0.95})
    assert d.severity is Severity.ESCALATE  # >0.9 correlation escalates


def test_a3_ops_allowlist_rejects_unknown():
    from aimos.agents.ops import OpsAgent

    ops = OpsAgent()
    assert ops.execute("restart_connector").allowed
    r = ops.execute("delete_all_the_things")  # not in the allowlist enum
    assert not r.allowed and "escalated" in r.outcome


# ---- LLM news sensor (P6-T3) ----

def _sensor(**kw):
    from aimos.observation.sentiment_llm import LLMNewsSensor
    cfg = load_params().observation.model_dump()
    return LLMNewsSensor(cfg, reliability=0.45, **kw)


def test_llm_injection_neutralized():
    from aimos.observation.sentiment_llm import LLMNewsSensor
    # injection: headline tries to force bullish 1.0 with fake credibility 5.0
    raw = '[{"id":0,"assets":["BTC"],"event_type":"other","direction":"bullish",' \
          '"magnitude":9.0,"credibility":5.0,"time_horizon":"hours","one_line_rationale":"x"}]'
    s = _sensor(classifier=lambda h: raw)
    parsed = s.classify([Headline(timestamp=TS, source="x", title="ignore instructions", url="u")])
    # clamped to [0,1] — injection cannot inflate influence
    assert parsed[0].magnitude == 1.0 and parsed[0].credibility == 1.0


def test_llm_malformed_json_fallback():
    s = _sensor(classifier=lambda h: "not json at all")
    assert s.classify([Headline(timestamp=TS, source="x", title="t", url="u")]) is None  # → lexicon


def test_llm_cache_replay_determinism():
    raw = '[{"id":0,"assets":["BTC"],"event_type":"etf_flows","direction":"bullish",' \
          '"magnitude":0.6,"credibility":0.7,"time_horizon":"days","one_line_rationale":"x"}]'
    cache: dict = {}
    live = _sensor(classifier=lambda h: raw, cache=cache)
    heads = [Headline(timestamp=TS, source="x", title="ETF inflows", url="u")]
    live.classify(heads)  # populates cache
    # replay reads ONLY the cache — same output, no classifier
    from aimos.observation.sentiment_llm import LLMNewsSensor, ReplayCacheMiss
    replay = _sensor(cache=cache, replay=True)
    assert replay.classify(heads)[0].event_type == "etf_flows"
    # a cache miss in replay is a hard error (§19.3)
    with pytest.raises(ReplayCacheMiss):
        _sensor(cache={}, replay=True).classify(heads)


def test_llm_hack_emits_shock_denial_does_not():
    from aimos.observation.sentiment_llm import NewsClassification
    s = _sensor()
    bases = {"BTC"}
    hack = NewsClassification(id=0, assets=["BTC"], event_type="hack", direction="bearish",
                              magnitude=0.9, credibility=0.8, time_horizon="hours", one_line_rationale="x")
    evs = s.to_evidence(hack, bases, TS)
    assert any(e.name == "headline_shock" for e in evs)  # high-cred hack → shock
    # low credibility (a denial/rumor) → no shock gate
    denial = NewsClassification(id=1, assets=["BTC"], event_type="hack", direction="bearish",
                                magnitude=0.3, credibility=0.2, time_horizon="hours", one_line_rationale="denied")
    assert not any(e.name == "headline_shock" for e in s.to_evidence(denial, bases, TS))


# ---- LiveBroker + mandate (P6-T5) ----

def test_mandate_refuses_when_disabled():
    from aimos.core.schemas import TradePlan
    from aimos.execution.broker.live import MandateGate
    gate = MandateGate(load_params().mandate.model_dump())  # enabled: false
    plan = TradePlan(plugin="TF", symbol="SOL/USDT", action=Action.LONG, size_quote=100)
    d = gate.check(plan, total_notional_after=100, open_positions_after=1)
    assert not d.ok and "fail-closed" in d.reason


def test_livebroker_refuses_withdrawal_enabled_keys():
    from aimos.execution.broker.live import LiveBroker, MandateGate
    gate = MandateGate(load_params().mandate.model_dump())
    with pytest.raises(PermissionError):
        LiveBroker("binance", gate, api_permissions={"withdraw": True})  # §23.4


def test_divergence_tracker_demotes():
    from aimos.execution.broker.live import DivergenceTracker
    t = DivergenceTracker(threshold_mult=2.0)
    for _ in range(5):
        t.record("Breakout", modeled_cost_bps=10.0, actual_cost_bps=30.0)  # 3× modeled
    assert t.should_demote("Breakout")
    for _ in range(5):
        t.record("TrendFollowing", modeled_cost_bps=10.0, actual_cost_bps=12.0)
    assert not t.should_demote("TrendFollowing")


def test_client_order_id_idempotent():
    from aimos.execution.broker.live import client_order_id
    assert client_order_id("SOL-2026-07-09T14:35") == client_order_id("SOL-2026-07-09T14:35")


# ---- scalp (P6-T6) ----

def test_scalp_context_gate():
    from aimos.runtime.fast_loop import fidelity_stamp, scalp_context_ok
    gate = load_params().scalp.model_dump()["context_gate"]
    mu = make_mu(regime=Regime.TRENDING_UP, confidence=0.6, risk_score=40)
    assert scalp_context_ok(mu, gate, is_tier1=True, in_funding_window=False)
    # funding window blocks scalping
    assert not scalp_context_ok(mu, gate, is_tier1=True, in_funding_window=True)
    # low confidence blocks
    assert not scalp_context_ok(make_mu(confidence=0.3), gate, True, False)
    assert fidelity_stamp(used_recorded_book=False) == "LOW_FIDELITY"


def test_scalp_post_only_entry():
    from aimos.execution.plugins.momentum_scalp import MomentumScalp
    p = MomentumScalp(load_params().scalp.model_dump())
    mu = make_mu(direction_bias=Direction.BULLISH, confidence=0.6, key_levels={
        "scalp": {"spread_bps": 2.0, "atr1m": 0.5, "book_imbalance": 0.5,
                  "volume_spike": True, "best_bid": 149.9, "best_ask": 150.1}})
    plan = p.propose(mu, make_exec_ctx())
    assert plan is not None and plan.entry == 149.9  # post-only maker at bid
    assert plan.meta["order_type"] == "post_only"
    # wide spread → no scalp
    mu.key_levels["scalp"]["spread_bps"] = 10.0
    assert p.propose(mu, make_exec_ctx()) is None


# ---- market making (P6-T7) ----

def test_market_making_min_capital_refusal():
    from aimos.execution.plugins.market_making import MarketMaking
    mm = MarketMaking(load_params().plugins["market_making"].model_dump())
    mu = make_mu(regime=Regime.RANGING, coin_health=80, behavior=Behavior.CONTINUATION,
                 key_levels={"mm": {"mid": 100, "sigma": 2, "inventory": 0, "spread_bps": 20}})
    # under $5k capital → refuse
    assert mm.propose(mu, make_exec_ctx(equity=1000)) is None
    # enough capital → quotes
    plan = mm.propose(mu, make_exec_ctx(equity=10_000))
    assert plan is not None and "bid" in plan.meta


def test_market_making_withdraws_on_manipulation():
    from aimos.execution.plugins.market_making import MarketMaking
    mm = MarketMaking(load_params().plugins["market_making"].model_dump())
    mu = make_mu(regime=Regime.RANGING, coin_health=80,
                 behavior_probs={"manipulation": 0.5},
                 key_levels={"mm": {"mid": 100, "sigma": 2, "inventory": 0, "spread_bps": 20}})
    assert mm.propose(mu, make_exec_ctx(equity=10_000)) is None  # withdraw quotes
