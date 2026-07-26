"""Exchange websocket streaming adapter for the runtime.

Provides a normalized, exchange-agnostic stream of top-of-book, trades, and
mini-ticker events. Concrete implementations live here; the runtime consumes the
normalized events and feeds them into ``MarketContext.orderbook_window``.

Recording is built-in so any live session can be replayed deterministically
(``RecordedStreamSource`` in ``aimos/data/streams.py``).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Iterable


@dataclass
class StreamEvent:
    type: str  # "trade" | "book" | "ticker" | "liquidation" | "heartbeat"
    timestamp: datetime
    venue: str
    symbol: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "venue": self.venue,
            "symbol": self.symbol,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "StreamEvent":
        return cls(
            type=raw["type"],
            timestamp=datetime.fromisoformat(raw["timestamp"]),
            venue=raw["venue"],
            symbol=raw["symbol"],
            data=raw.get("data", {}),
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _binance_symbol(symbol: str) -> str:
    """``BTC/USDT`` -> ``btcusdt`` for Binance stream names."""
    return symbol.replace("/", "").lower()


def _normalize_symbol(stream_symbol: str) -> str:
    """Best-effort reverse of ``_binance_symbol`` for display/journaling."""
    # Insert slash before the last 4 chars (USDT) or 3 (BTC/ETH as quote?)
    s = stream_symbol.upper()
    for quote in ("USDT", "USDC", "BTC", "ETH", "FDUSD", "TRY", "BNB"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return s


class StreamRecorder:
    """Append normalized events to a date-stamped JSONL file for replay."""

    def __init__(self, root: Path | str = "state/streams") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._file: Path | None = None
        self._fh: object | None = None

    def _ensure_open(self) -> None:
        if self._fh is not None and self._file is not None:
            return
        name = _utcnow().strftime("%Y-%m-%d") + ".jsonl"
        self._file = self.root / name
        self._fh = self._file.open("a", encoding="utf-8")

    def write(self, event: StreamEvent) -> None:
        self._ensure_open()
        self._fh.write(json.dumps(event.to_dict(), default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._file = None


class BinanceWebsocketSource:
    """Normalized websocket feed for Binance spot (public combined stream).

    Streams: ``<symbol>@trade``, ``<symbol>@depth``, ``<symbol>@miniTicker``.
    Events are pushed to an internal queue consumed by ``events()``.
    """

    def __init__(
        self,
        symbols: Iterable[str],
        venue: str = "binance",
        recorder: StreamRecorder | None = None,
        feed: "StreamFeed | None" = None,
    ) -> None:
        self.venue = venue
        self.symbols = list(symbols)
        self._recorder = recorder
        self._feed = feed
        self._queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._running = False

    @property
    def streams(self) -> list[str]:
        out = []
        for s in self.symbols:
            bs = _binance_symbol(s)
            out.extend([f"{bs}@trade", f"{bs}@depth", f"{bs}@miniTicker"])
        return out

    async def events(self) -> AsyncIterator[StreamEvent]:
        while self._running or not self._queue.empty():
            try:
                yield await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

    async def run(self) -> None:
        """Connect and keep streaming until cancelled."""
        import websockets

        self._running = True
        # combined stream endpoint: /stream?streams=a@trade/b@trade
        query = "/".join(self.streams)
        url = f"wss://stream.binance.com:9443/stream?streams={query}"
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    async for raw in ws:
                        await self._handle(raw)
            except Exception:  # noqa: BLE001 — the stream must not die on transient errors
                await asyncio.sleep(2.0)

    async def _handle(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        stream = payload.get("stream", "")
        data = payload.get("data", {})
        symbol = _normalize_symbol(stream.split("@")[0]) if "@" in stream else ""
        event = self._to_event(stream, symbol, data)
        if event is not None:
            if self._feed:
                self._feed.handle(event)
            if self._recorder:
                self._recorder.write(event)
            await self._queue.put(event)

    def _to_event(self, stream: str, symbol: str, data: dict) -> StreamEvent | None:
        etype = ""
        if stream.endswith("@trade"):
            etype = "trade"
        elif stream.endswith("@depth"):
            etype = "book"
        elif stream.endswith("@miniTicker"):
            etype = "ticker"
        else:
            return None

        ts = _utcnow()
        if "E" in data:
            try:
                ts = datetime.fromtimestamp(int(data["E"]) / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError):
                pass
        normalized = self._normalize_payload(etype, data)
        return StreamEvent(
            type=etype, timestamp=ts, venue=self.venue, symbol=symbol, data=normalized,
        )

    def _normalize_payload(self, etype: str, data: dict) -> dict:
        if etype == "trade":
            return {
                "price": float(data.get("p", 0.0)),
                "qty": float(data.get("q", 0.0)),
                "buyer_is_maker": data.get("m", False),
                "trade_id": data.get("t"),
            }
        if etype == "book":
            bids = [[float(p), float(q)] for p, q in data.get("b", [])]
            asks = [[float(p), float(q)] for p, q in data.get("a", [])]
            return {"bids": bids, "asks": asks, "last_update_id": data.get("u")}
        if etype == "ticker":
            return {
                "open": float(data.get("o", 0.0)),
                "high": float(data.get("h", 0.0)),
                "low": float(data.get("l", 0.0)),
                "close": float(data.get("c", 0.0)),
                "volume": float(data.get("v", 0.0)),
                "quote_volume": float(data.get("q", 0.0)),
            }
        return dict(data)

    def stop(self) -> None:
        self._running = False
