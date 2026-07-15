"""End-to-end paper-loop tests (§10.1 wiring — runnable-without-keys)."""

from __future__ import annotations

import asyncio

from aimos.core.config import load_params
from aimos.data.live_source import SyntheticSource, base_of
from aimos.runtime.paper_trader import run_paper
from aimos.telegram.sink import TelegramSink


def test_paper_loop_runs_offline_no_keys():
    # fully offline (synthetic data), no exchange/telegram keys → completes
    summary = asyncio.run(run_paper(offline=True, max_ticks=3))
    assert summary.ticks == 3
    assert summary.decisions == 6  # 2 dev symbols × 3 ticks
    assert summary.decisions == summary.trades_opened + summary.no_trades
    assert summary.final_equity > 0


def test_paper_loop_is_deterministic_offline():
    a = asyncio.run(run_paper(offline=True, max_ticks=2))
    b = asyncio.run(run_paper(offline=True, max_ticks=2))
    # synthetic source is seeded → identical decisions/equity (replay-stable)
    assert a.decisions == b.decisions
    assert a.final_equity == b.final_equity


def test_paper_loop_telegram_dry_run_captures_messages():
    params = load_params()
    # enable telegram; no token → dry-run (logs/captures, never sends)
    params.features.telegram_enabled = True
    summary = asyncio.run(run_paper(params=params, offline=True, max_ticks=1))
    assert summary.telegram_messages  # start + done messages captured
    assert any("AIMOS" in m for m in summary.telegram_messages)


def test_feature_flags_present_in_config():
    p = load_params()
    features = p.features.model_dump()
    assert set(features) >= {"telegram_enabled", "live_data", "llm_news_sensor", "scalp_enabled"}
    paper = p.paper.model_dump()
    assert paper["symbols"] and "starting_equity_usdt" in paper


def test_telegram_sink_dry_run_without_token():
    sink = TelegramSink(token="", dry_run=True)
    sink.send("hello")
    assert sink.sent == ["hello"]  # captured, not sent


def test_synthetic_source_shape():
    df = SyntheticSource(seed=1).fetch("BTC/USDT", "1h", 50)
    assert len(df) == 50
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "synthetic"]
    assert base_of("BTC/USDT") == "BTC"
