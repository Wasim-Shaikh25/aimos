"""Trading-universe assembly for the runtime (§16.1 A-B, cards P15-T1/T2).

Turns exchange market listings into the filtered, tiered set of bases the loop
analyzes each tick — replacing the old hardcoded 2-symbol dev set.

* **Live:** real ccxt ``load_markets()`` → ``discover`` → structural filters →
  tiering. Runs automatically when the runtime has exchange access.
* **Offline / network-blocked:** a bundled seed of top Binance USDT pairs
  (``seed_universe.json``, ordered by typical volume rank) so the full universe
  is still demonstrable with no network.

Selection is **filtered top-N by volume rank** (the chosen policy): keep every
market that clears the structural stable-quote/leveraged/active filters, then
analyze the top ``max_symbols`` by rank each tick. The full discovered set is
still exposed to the UI via the matrix. Not in the magic-number-linted layers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from aimos.universe.discovery import MarketInfo, discover
from aimos.universe.filters import filter_market
from aimos.universe.intersection import build_matrix, common
from aimos.universe.registry import Registry

log = structlog.get_logger(__name__)
_SEED = Path(__file__).resolve().parent / "seed_universe.json"


@dataclass
class Universe:
    registry: Registry
    order: list[str]                     # bases in volume-rank order (filtered)
    selected: list[str]                  # top-N bases the loop analyzes
    symbols: list[str]                   # "BASE/USDT" for the selected bases
    rejections: dict[str, int] = field(default_factory=dict)
    tiers: dict[str, str] = field(default_factory=dict)   # base -> "t1"/"t2"
    source: str = "seed"
    total_discovered: int = 0

    def matrix(self) -> dict[str, dict[str, bool]]:
        """base -> {venue: present} for the whole discovered universe (§16.1C)."""
        return build_matrix(self.registry)

    def cross_venue_bases(self, min_venues: int = 2) -> set[str]:
        return common(self.registry, min_venues=min_venues)


def _seed_markets(quote: str) -> tuple[list[MarketInfo], list[str]]:
    data = json.loads(_SEED.read_text(encoding="utf-8"))
    markets: list[MarketInfo] = []
    order: list[str] = []
    for row in data["markets"]:
        base = row["base"]
        order.append(base)
        for venue in row["venues"]:
            markets.append(MarketInfo(
                exchange=venue, symbol=f"{base}/{quote}", base=base, quote=quote,
                type="spot", active=True, min_notional=5.0, lot_step=0.0,
                taker_bps=7.5, maker_bps=2.0,
            ))
    return markets, order


def _live_markets(exchange_id: str, quote: str) -> tuple[list[MarketInfo], list[str]]:
    """Real ccxt discovery. Order is by quoteVolume when tickers are available."""
    from aimos.data.connectors.ccxt_connector import _load_ccxt  # lazy

    ccxt = _load_ccxt()
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    raw = ex.load_markets()
    markets = discover(exchange_id, raw)
    order: list[str] = []
    try:  # rank by 24h quote volume when the venue exposes tickers
        tickers = ex.fetch_tickers()
        ranked = sorted(
            (m for m in markets if m.quote.upper() == quote),
            key=lambda m: float((tickers.get(m.symbol) or {}).get("quoteVolume") or 0.0),
            reverse=True,
        )
        seen: set[str] = set()
        for m in ranked:
            if m.base not in seen:
                seen.add(m.base)
                order.append(m.base)
    except Exception:  # noqa: BLE001 — no tickers → fall back to listing order
        seen = set()
        for m in markets:
            if m.quote.upper() == quote and m.base not in seen:
                seen.add(m.base)
                order.append(m.base)
    return markets, order


def build_universe(
    exchange_id: str, universe_cfg: dict, *, live_data: bool, max_symbols: int,
    prefer_cross_venue: bool = False, min_venues: int = 2,
) -> Universe:
    """Assemble the tradable universe (live discovery or seed fallback).

    ``prefer_cross_venue`` biases the top-N toward assets that trade on
    ≥ ``min_venues`` venues (stable within volume rank) — used when cross-exchange
    arb is enabled so we don't spend arb slots on single-venue coins.
    """
    quotes = universe_cfg.get("quotes", {})
    primary = str(quotes.get("primary", "USDT")).upper()
    allowed = {q.upper() for q in quotes.get("allowed", ["USDT", "USDC"])}
    fcfg = universe_cfg.get("filters", {})
    exclude_bases = {b.upper() for b in fcfg.get("exclude_bases", [])}

    source = "seed"
    markets: list[MarketInfo]
    order: list[str]
    if live_data:
        try:
            markets, order = _live_markets(exchange_id, primary)
            source = f"live:{exchange_id}"
        except Exception:  # noqa: BLE001 — network blocked / ccxt absent → seed
            log.warning("universe_discovery_fell_back_to_seed", exchange=exchange_id)
            markets, order = _seed_markets(primary)
    else:
        markets, order = _seed_markets(primary)

    registry = Registry(primary_exchange=exchange_id)
    rejections: dict[str, int] = {}
    kept: set[str] = set()
    for m in markets:
        res = filter_market(
            m, None,  # structural filters only — quality metrics need live tickers
            allowed_quotes=allowed, exclude_bases=exclude_bases,
            exclude_leveraged_tokens=bool(fcfg.get("exclude_leveraged_tokens", True)),
            min_24h_volume_usd=0.0, min_book_depth_usd_0p5pct=0.0,
            max_spread_bps=float("inf"), min_listing_age_days=0.0,
        )
        if res.passed:
            registry.add_market(m)
            kept.add(m.base.upper())
        else:
            rejections[res.reason] = rejections.get(res.reason, 0) + 1

    ranked = [b for b in order if b.upper() in kept]
    # tiering stays by volume rank: first t1_max ranked bases are majors (§16.1)
    t1_max = int(universe_cfg.get("tiers", {}).get("t1_max", 12))
    tiers = {b: ("t1" if i < t1_max else "t2") for i, b in enumerate(ranked)}

    ordered = ranked
    if prefer_cross_venue:  # multi-venue coins first, volume order kept within group
        cross = {c.upper() for c in common(registry, min_venues=min_venues)}
        ordered = sorted(ranked, key=lambda b: 0 if b.upper() in cross else 1)
    selected = ordered[: max(1, int(max_symbols))]

    return Universe(
        registry=registry, order=ranked, selected=selected,
        symbols=[f"{b}/{primary}" for b in selected],
        rejections=rejections, tiers=tiers, source=source,
        total_discovered=len(kept),
    )


def _dev_universe(paper: dict) -> Universe:
    """A Universe over just the 2-symbol dev set (use_universe: false)."""
    from aimos.universe.registry import Registry
    bases = [s.split("/")[0] for s in paper["symbols"]]
    quote = (paper["symbols"][0].split("/")[1] if "/" in paper["symbols"][0] else "USDT")
    reg = Registry(primary_exchange=paper["data_exchange"])
    for b in bases:
        reg.add_market(MarketInfo(exchange=paper["data_exchange"], symbol=f"{b}/{quote}",
                                  base=b, quote=quote, type="spot", active=True,
                                  min_notional=5.0, lot_step=0.0, taker_bps=7.5, maker_bps=2.0))
    return Universe(registry=reg, order=bases, selected=bases, symbols=list(paper["symbols"]),
                    source="dev-set", total_discovered=len(bases),
                    tiers={b: "t1" for b in bases})


def runtime_universe(params, live_data: bool) -> Universe:
    """Universe for the live loop — shared by serve + paper_trader.

    Real top-N when ``paper.use_universe``, else the dev set. Biases toward
    multi-venue coins when cross-exchange arb is enabled (features flag).
    """
    paper = params.paper.model_dump()
    if not paper.get("use_universe", True):
        return _dev_universe(paper)
    ucfg = params.universe.model_dump()
    features = params.features.model_dump()
    return build_universe(
        paper["data_exchange"], ucfg, live_data=live_data,
        max_symbols=int(paper.get("max_symbols", 40)),
        prefer_cross_venue=bool(features.get("cross_exchange_enabled")),
        min_venues=int(ucfg.get("intersection", {}).get("min_venues", 2)),
    )


__all__ = ["Universe", "build_universe", "runtime_universe"]
