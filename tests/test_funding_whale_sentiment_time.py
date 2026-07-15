"""Funding + Whale + Sentiment + Time + Onchain tests (§5.7-5.10, §5.13 — P2-T5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aimos.core.clock import LiveClock
from aimos.core.schemas import (
    Direction,
    Headline,
    LargePrint,
    MarketContext,
    Timeframe,
)
from aimos.data.context import build_context
from aimos.data.funding import build_funding_frame
from aimos.observation.funding_engine import FundingEngine
from aimos.observation.onchain_engine import OnchainEngine
from aimos.observation.sentiment import SentimentEngine, fear_greed_strength
from aimos.observation.time_engine import TimeEngine
from aimos.observation.whale import WhaleEngine
from tests.conftest import obs_cfg, reliability

TS = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _ctx(**kw):
    return MarketContext(symbol="BTC", now=kw.pop("now", TS), **kw)


# ---- funding ----

def test_funding_extreme_contrarian():
    ms = int(TS.timestamp() * 1000)
    rates = [(ms + i * 3600_000, 0.0001) for i in range(39)]
    rates.append((ms + 39 * 3600_000, 0.005))  # positive spike
    fdf = build_funding_frame(rates)
    eng = FundingEngine(obs_cfg(), LiveClock(), reliability("funding"))
    evs = eng.observe(_ctx(funding=fdf))
    extreme = [e for e in evs if e.name == "funding_extreme"]
    assert extreme
    # positive funding extreme → contrarian BEARISH
    assert extreme[0].direction == Direction.BEARISH


# ---- whale ----

def test_whale_net_buys_bullish():
    prints = [
        LargePrint(timestamp=TS, symbol="BTC", side=Direction.BULLISH, notional_usd=500_000, price=100),
        LargePrint(timestamp=TS, symbol="BTC", side=Direction.BEARISH, notional_usd=100_000, price=100),
    ]
    eng = WhaleEngine(obs_cfg(), LiveClock(), reliability("whale"))
    evs = eng.observe(_ctx(trades_large=prints))
    assert evs and evs[0].name == "large_buys"
    assert evs[0].direction == Direction.BULLISH


# ---- sentiment ----

def _sentiment():
    return SentimentEngine(obs_cfg(), LiveClock(), reliability("sentiment"))


def test_news_tone_bullish():
    heads = [Headline(timestamp=TS, source="cd", title="ETF approval and partnership upgrade", url="u1")]
    evs = _sentiment().observe(_ctx(headlines=heads))
    tone = [e for e in evs if e.name == "news_tone"]
    assert tone and tone[0].direction == Direction.BULLISH


def test_headline_shock_fires_on_hack():
    heads = [Headline(timestamp=TS, source="cd", title="Major exchange hack drains funds", url="u2")]
    evs = _sentiment().observe(_ctx(headlines=heads))
    shock = [e for e in evs if e.name == "headline_shock"]
    assert shock
    assert shock[0].meta.get("risk_gate") is True


def test_hack_denial_does_not_trigger_shock():
    # negation guard: "denies hack" must NOT fire headline_shock (§5.10 note)
    heads = [Headline(timestamp=TS, source="cd", title="Exchange denies hack rumors", url="u3")]
    evs = _sentiment().observe(_ctx(headlines=heads))
    assert not [e for e in evs if e.name == "headline_shock"]


def test_fear_greed_helper():
    d, s = fear_greed_strength(10, low=20, high=80, div=20)
    assert d == Direction.BULLISH and s > 0
    d, s = fear_greed_strength(90, low=20, high=80, div=20)
    assert d == Direction.BEARISH
    d, s = fear_greed_strength(50, low=20, high=80, div=20)
    assert d == Direction.NEUTRAL and s == 0.0


# ---- time ----

def _time():
    return TimeEngine(obs_cfg(), LiveClock(), reliability("time"))


def test_time_session_and_funding_window():
    # 08:05 UTC → europe session, and within 30min of the 08:00 funding settlement
    now = datetime(2026, 7, 9, 8, 5, tzinfo=timezone.utc)
    evs = _time().observe(_ctx(now=now))
    names = {e.name for e in evs}
    session = [e for e in evs if e.name == "session"][0]
    assert session.meta["session"] == "europe"
    assert "funding_window" in names


def test_time_weekend_flag():
    saturday = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)  # a Saturday
    evs = _time().observe(_ctx(now=saturday))
    assert "weekend" in {e.name for e in evs}


# ---- onchain stub ----

def test_onchain_inert():
    eng = OnchainEngine(obs_cfg(), LiveClock(), reliability("onchain"))
    assert eng.observe(_ctx()) == []
