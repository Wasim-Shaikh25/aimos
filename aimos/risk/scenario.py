"""Scenario & stress engine (§24.1, card P5-T7).

What-if analysis on the CURRENT book: shock each position by its BTC-beta, reprice
PnL, and gate new risk-increasing trades when any binding scenario shows a loss
beyond ``max_scenario_loss_pct``. Config-driven (config/scenarios.yaml).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from aimos.core.schemas import Action, Position


@dataclass
class PositionRisk:
    symbol: str
    notional_usd: float
    side: Action
    beta: float  # btc_beta (§5.12)


@dataclass
class ScenarioResult:
    name: str
    pnl_pct: float  # portfolio PnL as % of equity
    breaches_gate: bool


def scenario_pnl(
    positions: Sequence[PositionRisk],
    equity: float,
    btc_shock: float,
    alt_extra: float = 0.0,
) -> float:
    """Portfolio PnL % under a BTC shock propagated by beta (§24.1).

    Each position moves ``beta × btc_shock`` (+ ``alt_extra`` for non-BTC).
    Longs profit on positive shocks, shorts profit on negative.
    """
    if equity <= 0:
        return 0.0
    pnl = 0.0
    for p in positions:
        move = p.beta * btc_shock
        if p.symbol.upper() != "BTC":
            move += alt_extra
        sign = 1.0 if p.side is Action.LONG else -1.0
        pnl += p.notional_usd * move * sign
    return pnl / equity * 100.0


class ScenarioEngine:
    def __init__(self, scenarios_cfg: Mapping[str, Any]) -> None:
        self.cfg = scenarios_cfg
        self.max_loss = float(scenarios_cfg["max_scenario_loss_pct"])
        self.binding = set(scenarios_cfg["binding_set"])
        self.scenarios = scenarios_cfg["scenarios"]

    def run(self, positions: Sequence[PositionRisk], equity: float) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        for name, spec in self.scenarios.items():
            if not isinstance(spec, dict) or "shock" not in spec and "alt_extra" not in spec:
                continue
            shock_map = spec.get("shock", {})
            btc_shock = float(shock_map.get("BTC", spec.get("shock_pct", 0.0)))
            alt_extra = float(spec.get("alt_extra", 0.0))
            pnl = scenario_pnl(positions, equity, btc_shock, alt_extra)
            breaches = name in self.binding and pnl < -self.max_loss
            results.append(ScenarioResult(name, pnl, breaches))
        return results

    def blocks_new_risk(self, positions: Sequence[PositionRisk], equity: float) -> bool:
        """Hard gate (§24.1): any binding scenario over the loss cap blocks new risk."""
        return any(r.breaches_gate for r in self.run(positions, equity))


__all__ = ["PositionRisk", "ScenarioEngine", "ScenarioResult", "scenario_pnl"]
