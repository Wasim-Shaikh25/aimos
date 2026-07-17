"""Simulated multi-venue balances + two-leg arb execution + performance (Phase B).

Sits alongside ``PaperBroker`` (which handles directional trades). This module:

* keeps a per-venue **balance sheet** (USDT split across venues),
* executes a cross-exchange arb decision as **two simultaneous legs** — buy on the
  cheap venue, sell on the rich venue — realizing the net spread after fees, and
* records every arb into a **trade ledger** for the Trade History screen.

Fully simulated (no keys, no real orders). The live equivalent (per-venue
``LiveVenueBroker`` + real order placement) plugs into the same shape in Phase D.
Not in the magic-number-linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from aimos.core.normalize import BPS, PCT


@dataclass
class MultiVenueSim:
    venues: list[str]
    start_usdt_total: float
    taker_bps: float
    balances: dict = field(default_factory=dict)   # venue -> {asset: free}
    trades: list = field(default_factory=list)     # arb trade records
    realized_arb: float = 0.0
    _n: int = 0

    def __post_init__(self) -> None:
        per = self.start_usdt_total / max(len(self.venues), 1)
        self.balances = {v: {"USDT": per} for v in self.venues}

    def execute_arb(
        self, base: str, buy_venue: str, sell_venue: str, buy_price: float,
        sell_price: float, notional_usd: float, now: datetime,
    ) -> float:
        """Buy on the cheap venue, sell on the rich venue; realize the net spread.

        A completed arb ends flat in ``base`` (bought and sold the same qty) and up
        (or down) in USDT — so the balance sheet tracks USDT shifting from the buy
        venue to the sell venue, which is exactly why live arb needs inventory on
        both sides (Phase D). Returns the net PnL in USDT.
        """
        if buy_price <= 0 or sell_price <= 0 or notional_usd <= 0:
            return 0.0
        # inventory constraint: can't buy with USDT the buy venue doesn't hold, so
        # size the arb down to the available balance (throttles when a venue runs
        # dry — the real reason live arb needs pre-funded inventory + rebalancing).
        avail = self.balances.get(buy_venue, {}).get("USDT", 0.0)
        notional_usd = min(notional_usd, avail)
        if notional_usd <= 1.0:
            return 0.0  # buy venue out of inventory → skip this arb
        qty = notional_usd / buy_price
        buy_fee = notional_usd * self.taker_bps / BPS
        proceeds = qty * sell_price
        sell_fee = proceeds * self.taker_bps / BPS
        pnl = proceeds - notional_usd - buy_fee - sell_fee

        self.balances.setdefault(buy_venue, {})["USDT"] = \
            self.balances.get(buy_venue, {}).get("USDT", 0.0) - notional_usd - buy_fee
        self.balances.setdefault(sell_venue, {})["USDT"] = \
            self.balances.get(sell_venue, {}).get("USDT", 0.0) + proceeds - sell_fee
        self.realized_arb += pnl
        self._n += 1
        self.trades.append({  # raw floats — the serve payload / UI formats for display
            "kind": "arb", "symbol": base, "strategy": "CrossExchangeArb",
            "venue": f"{buy_venue}→{sell_venue}", "side": "buy/sell",
            "qty": qty, "entry": buy_price, "exit": sell_price,
            "pnl_usd": pnl, "opened_at": now.isoformat(),
            "closed_at": now.isoformat(), "result": "captured", "status": "closed",
        })
        return pnl

    # -- read models for the dashboards -------------------------------------

    def balances_rows(self) -> list[dict]:
        rows = []
        for v in sorted(set(self.venues) | set(self.balances)):
            usdt = self.balances.get(v, {}).get("USDT", 0.0)
            rows.append({"venue": v, "usdt": usdt,
                         "assets": {a: x for a, x in self.balances.get(v, {}).items()
                                    if a != "USDT" and x != 0.0}})
        return rows

    def total_usdt(self) -> float:
        return sum(b.get("USDT", 0.0) for b in self.balances.values())


def performance(directional_trades: list, arb_trades: list, equity_curve: list) -> dict:
    """Realized PnL, win rate, and per-strategy / per-venue breakdowns (§5.6)."""
    closed = [t for t in (directional_trades + arb_trades) if t["status"] == "closed"]
    wins = [t for t in closed if t["pnl_usd"] > 0]
    realized = sum(t["pnl_usd"] for t in closed)
    by_strategy: dict = {}
    by_venue: dict = {}
    for t in closed:
        s = by_strategy.setdefault(t["strategy"], {"trades": 0, "pnl_usd": 0.0})
        s["trades"] += 1
        s["pnl_usd"] = s["pnl_usd"] + t["pnl_usd"]
        v = by_venue.setdefault(t["venue"], {"trades": 0, "pnl_usd": 0.0})
        v["trades"] += 1
        v["pnl_usd"] = v["pnl_usd"] + t["pnl_usd"]
    curve = equity_curve or []
    peak, max_dd = (curve[0] if curve else 0.0), 0.0
    for e in curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    n_closed_dir = len([t for t in directional_trades if t["status"] == "closed"])
    return {
        "closed_trades": len(closed), "open_trades": len(directional_trades) - n_closed_dir,
        "realized_pnl_usd": realized,
        "win_rate": (len(wins) / len(closed)) if closed else 0.0,
        "arb_trades": len(arb_trades), "arb_pnl_usd": sum(t["pnl_usd"] for t in arb_trades),
        "max_drawdown_pct": max_dd * PCT,
        "by_strategy": by_strategy, "by_venue": by_venue,
        "equity_start": curve[0] if curve else None, "equity_last": curve[-1] if curve else None,
    }


__all__ = ["MultiVenueSim", "performance"]
