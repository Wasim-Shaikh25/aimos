"""Streaming event normalization and recorder."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from aimos.data.streaming import BinanceWebsocketSource, StreamEvent, StreamRecorder


def test_stream_recorder_writes_jsonl(tmp_path):
    rec = StreamRecorder(tmp_path)
    ev = StreamEvent(
        type="trade", timestamp=datetime.now(timezone.utc),
        venue="binance", symbol="BTC/USDT", data={"price": 70000.0},
    )
    rec.write(ev)
    rec.close()

    files = list(tmp_path.glob("*.jsonl"))
    assert files
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["type"] == "trade"
    assert parsed["symbol"] == "BTC/USDT"


def test_binance_source_normalizes_trade():
    source = BinanceWebsocketSource(["BTC/USDT"])
    data = {"p": "70000.00", "q": "0.100", "m": True, "t": 12345, "E": 1735689600000}
    event = source._to_event("btcusdt@trade", "BTC/USDT", data)
    assert event is not None
    assert event.type == "trade"
    assert event.venue == "binance"
    assert event.data["price"] == 70000.0
    assert event.data["buyer_is_maker"] is True
