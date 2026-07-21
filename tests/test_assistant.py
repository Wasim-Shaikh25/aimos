"""Read-only AI analyst: grounding, prompting, API, and Telegram — no network.

The LLM caller is injected, so every test is deterministic and offline. Covers
that answers are grounded in the provided evidence, that the analyst is read-only,
timeframe filtering, and the disabled paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from aimos.runtime.assistant import (
    Assistant, AssistantDisabled, anthropic_caller, build_grounding, _parse_timeframe,
)


def _providers():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=3)).isoformat()
    fresh = (now - timedelta(minutes=30)).isoformat()
    return {
        "decisions": lambda limit=40: [
            {"decision_id": "d-fresh", "timestamp": fresh, "symbol": "BTC", "regime": "trending_up",
             "action": "long", "plugin": "TrendFollowing", "p_up": 0.6, "confidence": 0.7, "reasons": ["x"]},
            {"decision_id": "d-old", "timestamp": old, "symbol": "ETH", "regime": "ranging",
             "action": "no_trade", "plugin": "RiskOff", "p_up": 0.5, "confidence": 0.3, "reasons": ["y"]},
        ],
        "performance": lambda: {"realized_pnl_usd": 12.5, "win_rate": 0.55},
        "models": lambda: {"models": [{"name": "MLEngine", "status": "shadow (weight 0)"}],
                           "fusion_weights": {"ml": 0.0}},
        "monitor": lambda: {"coverage_pct": 92.3, "summary": {"ok": 12, "failing": 0}},
        "features": lambda: {"features": {"scalp": True}},
        "golive": lambda: {"percent": 0},
        "strategies": lambda: {"strategies": [{"name": "TrendFollowing", "chosen": 3}]},
        "equity": lambda: [10000.0, 10012.5],
    }


# -- grounding ---------------------------------------------------------------

def test_build_grounding_has_all_sections():
    g = build_grounding(_providers())
    for key in ("decisions", "performance", "models", "monitor", "features", "golive",
                "strategies", "equity"):
        assert key in g
    assert g["equity"] == {"start": 10000.0, "last": 10012.5, "points": 2}
    assert g["n_decisions_in_bundle"] == 2


def test_timeframe_filters_old_decisions():
    g = build_grounding(_providers(), timeframe="24h")
    ids = {d["decision_id"] for d in g["decisions"]}
    assert ids == {"d-fresh"}          # the 3-day-old decision is outside 24h
    assert g["window"] == "24h"


@pytest.mark.parametrize("tf,exp", [("24h", timedelta(hours=24)), ("7d", timedelta(days=7)),
                                    ("30m", timedelta(minutes=30)), ("2w", timedelta(weeks=2)),
                                    ("bad", None), ("", None), ("10x", None)])
def test_parse_timeframe(tf, exp):
    assert _parse_timeframe(tf) == exp


def test_broken_provider_does_not_crash():
    def boom():
        raise RuntimeError("nope")
    g = build_grounding({"performance": boom, "decisions": lambda limit=40: []})
    assert g["performance"] == {}       # swallowed, analyst still builds a bundle


# -- analyst (injected caller) ----------------------------------------------

def test_answer_is_grounded_and_readonly():
    captured = {}

    def fake_caller(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        captured["kw"] = kw
        return "grounded answer citing d-fresh"

    a = Assistant(_providers(), cfg={"model": "m", "max_tokens": 50}, caller=fake_caller)
    out = a.answer("How did we do?")
    assert out["answer"] == "grounded answer citing d-fresh"
    # the evidence (journal state) was actually passed to the model
    assert "d-fresh" in captured["user"] and "EVIDENCE" in captured["user"]
    # read-only role is asserted in the system prompt
    assert "READ-ONLY" in captured["system"] and "CANNOT take actions" in captured["system"]
    assert captured["kw"]["model"] == "m" and captured["kw"]["max_tokens"] == 50
    assert out["grounded_on"]["decisions"] == 2


def test_report_uses_timeframe():
    seen = {}

    def fake_caller(system, user, **kw):
        seen["user"] = user
        return "report body"

    a = Assistant(_providers(), caller=fake_caller)
    out = a.report("7d")
    assert out["timeframe"] == "7d"
    assert out["report"] == "report body"
    assert "last 7d" in seen["user"]


def test_empty_question_no_llm_call():
    called = {"n": 0}

    def fake_caller(*a, **k):
        called["n"] += 1
        return "x"

    a = Assistant(_providers(), caller=fake_caller)
    a.answer("   ")
    assert called["n"] == 0   # empty question short-circuits — no spend


def test_anthropic_caller_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AssistantDisabled):
        anthropic_caller("s", "u", model="m", max_tokens=1, temperature=0.0, timeout=1.0)


# -- API ---------------------------------------------------------------------

def _client(assistant):
    from fastapi.testclient import TestClient
    from aimos.api.server import AppState, create_app
    from aimos.journal.journal import Journal
    return TestClient(create_app(AppState(journal=Journal(":memory:"), assistant=assistant)))


def test_api_disabled_returns_503():
    c = _client(None)
    assert c.get("/api/assistant").json() == {"enabled": False}
    assert c.post("/api/assistant", json={"question": "hi"}).status_code == 503
    assert c.get("/api/assistant/report").status_code == 503


def test_api_answers_and_reports():
    class Fake:
        def answer(self, q):
            return {"answer": f"A:{q}", "grounded_on": {"decisions": 1}}
        def report(self, tf):
            return {"report": f"R:{tf}", "timeframe": tf}
    c = _client(Fake())
    assert c.get("/api/assistant").json() == {"enabled": True}
    assert c.post("/api/assistant", json={"question": "why"}).json()["answer"] == "A:why"
    assert c.get("/api/assistant/report", params={"timeframe": "7d"}).json()["report"] == "R:7d"


# -- Telegram ----------------------------------------------------------------

def _router(assistant):
    from aimos.core.clock import LiveClock
    from aimos.telegram.bot import CommandRouter
    from aimos.telegram.security import ChatWhitelist, NonceStore
    return CommandRouter(ChatWhitelist({7}), NonceStore(LiveClock()), assistant=assistant)


def test_telegram_ask_and_report():
    class Fake:
        def answer(self, q):
            return {"answer": f"A:{q}"}
        def report(self, tf):
            return {"report": f"R:{tf}"}
    r = _router(Fake())
    assert r.handle(7, "/ask is the ml working") == "A:is the ml working"
    assert r.handle(7, "/report 7d") == "R:7d"
    assert r.handle(7, "/ask") .startswith("usage")


def test_telegram_ask_unavailable_when_no_assistant():
    r = _router(None)
    assert "not available" in r.handle(7, "/ask anything")
    # unauthorized chat stays silent
    assert r.handle(999, "/ask anything") is None
