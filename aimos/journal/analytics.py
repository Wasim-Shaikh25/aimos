"""Outcome analytics for per-strategy attribution (T-004).

Reads the journaled ``outcomes`` table, joins each outcome to its decision to
recover the strategy/plugin that produced the trade, and returns per-strategy
statistics suitable for ``/api/performance`` and ``/api/strategies``.
"""

from __future__ import annotations

import json
from typing import Any


_MIN_SAMPLE = 30


def _load(row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(row["payload"])


def _plugin_from_decision(payload: dict[str, Any]) -> str:
    chosen = payload.get("chosen") or {}
    return chosen.get("plugin") or "unknown"


def per_strategy_attribution(
    journal,
    min_sample: int = _MIN_SAMPLE,
    chosen_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return per-strategy trade statistics computed from the journal outcomes.

    The result is advisory only — no strategy is auto-disabled (§15.3).  A
    ``low_sample`` flag is set for any strategy with fewer than ``min_sample``
    trades so the UI/analyst can surface the caveat instead of trusting a tiny
    sample.
    """
    chosen_counts = chosen_counts or {}
    outcome_rows = journal.conn.execute(
        'SELECT decision_id, payload FROM outcomes ORDER BY seq'
    ).fetchall()

    if not outcome_rows:
        return {
            "per_strategy": {
                name: {
                    "trades": 0,
                    "win_rate": 0.0,
                    "pnl_quote": 0.0,
                    "pnl_r": 0.0,
                    "expectancy_r": 0.0,
                    "avg_mae_r": 0.0,
                    "avg_mfe_r": 0.0,
                    "avg_win_r": 0.0,
                    "avg_loss_r": 0.0,
                    "profit_loss_ratio": None,
                    "low_sample": True,
                    "chosen_count": count,
                }
                for name, count in chosen_counts.items()
            },
            "low_sample": True,
            "caveat": "no outcomes",
        }

    decision_ids = {row["decision_id"] for row in outcome_rows if row["decision_id"]}
    plugin_by_id: dict[str, str] = {}
    if decision_ids:
        placeholders = ",".join("?" * len(decision_ids))
        decision_rows = journal.conn.execute(
            f"SELECT decision_id, payload FROM decisions WHERE decision_id IN ({placeholders})",
            tuple(decision_ids),
        ).fetchall()
        for row in decision_rows:
            payload = _load(row)
            plugin_by_id[row["decision_id"]] = _plugin_from_decision(payload)

    accum: dict[str, dict[str, Any]] = {}
    for row in outcome_rows:
        payload = _load(row)
        plugin = plugin_by_id.get(row["decision_id"], "unknown")
        pnl_r = float(payload.get("pnl_r", 0.0))
        pnl_quote = float(payload.get("pnl_quote", 0.0))
        mae = float(payload.get("max_adverse_r", 0.0))
        mfe = float(payload.get("max_favorable_r", 0.0))

        s = accum.setdefault(
            plugin,
            {
                "trades": 0,
                "wins": 0,
                "pnl_quote": 0.0,
                "pnl_r": 0.0,
                "mae_sum": 0.0,
                "mfe_sum": 0.0,
                "positive_pnl_r_sum": 0.0,
                "positive_trades": 0,
                "negative_pnl_r_sum": 0.0,
                "negative_trades": 0,
            },
        )
        s["trades"] += 1
        s["pnl_quote"] += pnl_quote
        s["pnl_r"] += pnl_r
        s["mae_sum"] += mae
        s["mfe_sum"] += mfe
        if pnl_r > 0:
            s["wins"] += 1
            s["positive_pnl_r_sum"] += pnl_r
            s["positive_trades"] += 1
        elif pnl_r < 0:
            s["negative_pnl_r_sum"] += pnl_r
            s["negative_trades"] += 1

    per_strategy: dict[str, dict[str, Any]] = {}
    low_sample = False
    for plugin, s in accum.items():
        n = s["trades"]
        wins = s["wins"]
        win_rate = wins / n if n else 0.0
        avg_win = (
            s["positive_pnl_r_sum"] / s["positive_trades"]
            if s["positive_trades"]
            else 0.0
        )
        avg_loss = (
            s["negative_pnl_r_sum"] / s["negative_trades"]
            if s["negative_trades"]
            else 0.0
        )
        profit_loss_ratio = (
            round(avg_win / abs(avg_loss), 4) if avg_loss != 0 else None
        )
        expectancy_pl = (
            round(win_rate * (profit_loss_ratio or 0) - (1 - win_rate), 4)
            if profit_loss_ratio is not None
            else None
        )
        is_low = n < min_sample
        if is_low:
            low_sample = True
        per_strategy[plugin] = {
            "trades": n,
            "win_rate": round(win_rate, 4),
            "pnl_quote": round(s["pnl_quote"], 4),
            "pnl_r": round(s["pnl_r"], 4),
            "expectancy_r": round(s["pnl_r"] / n, 4) if n else 0.0,
            "expectancy_pl_ratio": expectancy_pl,
            "avg_mae_r": round(s["mae_sum"] / n, 4) if n else 0.0,
            "avg_mfe_r": round(s["mfe_sum"] / n, 4) if n else 0.0,
            "avg_win_r": round(avg_win, 4),
            "avg_loss_r": round(avg_loss, 4),
            "profit_loss_ratio": profit_loss_ratio,
            "low_sample": is_low,
            "chosen_count": chosen_counts.get(plugin, 0),
        }

    # Include strategies that have been chosen but have zero outcomes.
    for name, count in chosen_counts.items():
        if name not in per_strategy:
            per_strategy[name] = {
                "trades": 0,
                "win_rate": 0.0,
                "pnl_quote": 0.0,
                "pnl_r": 0.0,
                "expectancy_r": 0.0,
                "avg_mae_r": 0.0,
                "avg_mfe_r": 0.0,
                "avg_win_r": 0.0,
                "avg_loss_r": 0.0,
                "profit_loss_ratio": None,
                "low_sample": True,
                "chosen_count": count,
            }

    caveat = None
    if not outcome_rows:
        caveat = "no outcomes"
    elif low_sample:
        caveat = f"low sample (< {min_sample})"

    return {
        "per_strategy": per_strategy,
        "low_sample": low_sample,
        "caveat": caveat,
    }
