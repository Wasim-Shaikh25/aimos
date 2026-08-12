"""T-004 — per-strategy attribution from real outcomes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.journal.analytics import per_strategy_attribution
from aimos.journal.journal import Journal


def _make_journal(outcomes: list[dict], decisions: list[dict] | None = None) -> Journal:
    j = Journal(":memory:")
    decisions = decisions or []
    for d in decisions:
        j._append("decisions", d["decision_id"], d["symbol"], d["timestamp"], d["payload"])
    for o in outcomes:
        j._append("outcomes", o["decision_id"], None, o["timestamp"], o["payload"])
    return j


def test_per_strategy_counts_and_pnl():
    """T-004.1: 10 outcomes across 3 strategies."""
    decisions = [
        {"decision_id": "d1", "symbol": "BTC/USDT", "timestamp": "2026-01-01T00:00:00+00:00",
         "payload": {"chosen": {"plugin": "Breakout"}}},
        {"decision_id": "d2", "symbol": "ETH/USDT", "timestamp": "2026-01-01T00:00:00+00:00",
         "payload": {"chosen": {"plugin": "Pullback"}}},
        {"decision_id": "d3", "symbol": "SOL/USDT", "timestamp": "2026-01-01T00:00:00+00:00",
         "payload": {"chosen": {"plugin": "SmartDCA"}}},
    ]
    outcomes = []
    for i in range(7):
        outcomes.append({
            "decision_id": "d1", "timestamp": "2026-01-02T00:00:00+00:00",
            "payload": {"pnl_r": 1.0 if i % 2 == 0 else -0.5, "pnl_quote": 10.0 if i % 2 == 0 else -5.0,
                        "max_adverse_r": -0.3, "max_favorable_r": 1.2, "exit_reason": "tp"},
        })
    for i in range(2):
        outcomes.append({
            "decision_id": "d2", "timestamp": "2026-01-02T00:00:00+00:00",
            "payload": {"pnl_r": -0.2, "pnl_quote": -2.0, "max_adverse_r": -0.4,
                        "max_favorable_r": 0.5, "exit_reason": "sl"},
        })
    outcomes.append({
        "decision_id": "d3", "timestamp": "2026-01-02T00:00:00+00:00",
        "payload": {"pnl_r": 0.3, "pnl_quote": 3.0, "max_adverse_r": -0.1,
                    "max_favorable_r": 0.6, "exit_reason": "tp"},
    })
    j = _make_journal(outcomes, decisions)
    attr = per_strategy_attribution(j, chosen_counts={"Breakout": 10, "Pullback": 3, "SmartDCA": 1})

    by = attr["per_strategy"]
    assert by["Breakout"]["trades"] == 7
    assert by["Breakout"]["win_rate"] == pytest.approx(4 / 7, abs=0.01)
    assert by["Breakout"]["pnl_r"] == pytest.approx(2.5, abs=0.01)
    assert by["Pullback"]["trades"] == 2
    assert by["Pullback"]["pnl_r"] == pytest.approx(-0.4, abs=0.01)
    assert by["SmartDCA"]["trades"] == 1
    assert by["SmartDCA"]["low_sample"] is True
    assert attr["low_sample"] is True


def test_low_sample_caveat():
    """T-004.2: n < 30 surfaces a caveat."""
    decisions = [{"decision_id": "d1", "symbol": "BTC/USDT", "timestamp": "2026-01-01T00:00:00+00:00",
                  "payload": {"chosen": {"plugin": "Breakout"}}}]
    outcomes = [{
        "decision_id": "d1", "timestamp": "2026-01-02T00:00:00+00:00",
        "payload": {"pnl_r": 1.0, "pnl_quote": 10.0, "max_adverse_r": -0.1,
                    "max_favorable_r": 1.0, "exit_reason": "tp"},
    }]
    j = _make_journal(outcomes, decisions)
    attr = per_strategy_attribution(j)
    assert attr["low_sample"] is True
    assert attr["caveat"].startswith("low sample")
    assert attr["per_strategy"]["Breakout"]["low_sample"] is True


def test_zero_outcomes_returns_empty():
    """T-004.3: zero outcomes returns a graceful empty result."""
    j = Journal(":memory:")
    attr = per_strategy_attribution(j)
    assert attr["per_strategy"] == {}
    assert attr["low_sample"] is True
    assert attr["caveat"] == "no outcomes"


def test_losing_strategy_not_disabled():
    """T-004.4: a losing strategy is reported, not auto-disabled."""
    decisions = [{"decision_id": "d1", "symbol": "BTC/USDT", "timestamp": "2026-01-01T00:00:00+00:00",
                  "payload": {"chosen": {"plugin": "Breakout"}}}]
    outcomes = [{
        "decision_id": "d1", "timestamp": "2026-01-02T00:00:00+00:00",
        "payload": {"pnl_r": -2.0, "pnl_quote": -20.0, "max_adverse_r": -2.0,
                    "max_favorable_r": 0.2, "exit_reason": "sl"},
    }]
    j = _make_journal(outcomes, decisions)
    attr = per_strategy_attribution(j)
    strat = attr["per_strategy"]["Breakout"]
    assert strat["pnl_r"] == -2.0
    assert strat["pnl_quote"] == -20.0
    # No 'enabled' field is changed; the function does not mutate config.
    assert "enabled" not in strat
