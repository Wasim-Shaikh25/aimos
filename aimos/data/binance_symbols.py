"""Fetch the current Binance spot USDT trading universe without requiring ccxt.

Used by offline download/validation scripts so a full 12-month dataset can be
built from free Binance Vision klines for every currently trading pair.
"""

from __future__ import annotations

import httpx

_STABLE_BASES = {
    "BUSD", "DAI", "FDUSD", "PAX", "PYUSD", "TGBP", "TUSD",
    "USDC", "USDD", "USDP", "USDS", "USD1", "UST",
}


async def all_binance_usdt_spot_symbols(
    top_n: int | None = None,
    include_stable: bool = False,
    api_base: str = "https://www.binance.com/api/v3",
) -> list[str]:
    """Return "BASE/USDT" symbols for all currently trading non-stable spot pairs.

    Optionally keep only the top-N by 24h quote volume. Stablecoin bases are
    excluded by default because they produce near-zero trading signals and would
    otherwise dominate a simple volume-based top-N.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.get(f"{api_base}/exchangeInfo")
        r.raise_for_status()
        records = [
            s
            for s in r.json()["symbols"]
            if s.get("status") == "TRADING"
            and s.get("quoteAsset") == "USDT"
            and s.get("isSpotTradingAllowed", True)
            and (include_stable or s.get("baseAsset", "") not in _STABLE_BASES)
        ]

        if top_n and top_n > 0:
            tickers = await client.get(f"{api_base}/ticker/24hr")
            tickers.raise_for_status()
            by_symbol = {t["symbol"]: float(t.get("quoteVolume", 0) or 0) for t in tickers.json()}
            records = sorted(
                records, key=lambda s: by_symbol.get(s["symbol"], 0.0), reverse=True
            )[:top_n]

    return [f"{rec['baseAsset']}/{rec['quoteAsset']}" for rec in records]
