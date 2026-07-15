"""Portfolio risk manager — hard gates run AFTER the evaluator (§7.4, §16.4,
§23.10B, card P4-T3).

Each gate can veto: it converts the chosen plan to NO_TRADE with a reason. Gates
1-12 (heat, positions, per-symbol, correlation buckets, daily stop, risk-score
veto, kill switch, T1 gate, intersection gate, protections, per-asset/bucket
allocation, stablecoin reserve floor). External state (open risk, day PnL, tier
membership, active protection locks) arrives in ``RiskState`` so this stays pure
and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from aimos.core.normalize import PCT
from aimos.core.schemas import Action, ExecContext, MarketUnderstanding, TradePlan

# plugins exempt from the risk_score veto (§7.4 rule 4)
_RISK_VETO_EXEMPT = {"RiskOff", "SmartDCA"}


@dataclass
class RiskState:
    """Portfolio aggregates + gate inputs (supplied by the runtime)."""

    open_risk_pct: float = 0.0  # Σ open-position risk (% equity)
    open_positions: int = 0
    day_pnl_pct: float = 0.0
    kill_switch: bool = False
    is_tier1: bool = True  # asset is Tier 1 + passes filters now (§16.4)
    is_cross_venue: bool = False
    intersection_ok: bool = True  # both legs live on ≥ min_venues (§16.1C)
    protection_locked: bool = False  # a §21.1 guard locked this symbol/globally
    bucket_risk_pct: float = 0.0  # existing risk in this plan's correlation bucket
    per_asset_alloc_pct: float = 0.0  # existing notional on this asset (% equity)
    bucket_alloc_pct: float = 0.0  # existing notional in this bucket (% equity)
    reserve_pct: float = PCT  # currently unallocated (% equity), default fully unallocated


@dataclass
class RiskDecision:
    plan: TradePlan
    vetoed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, exec_cfg: Mapping[str, Any], capacity_cfg: Mapping[str, Any]) -> None:
        self.cfg = exec_cfg
        self.cap = capacity_cfg
        self.div = capacity_cfg["diversification"]

    def check(
        self,
        plan: TradePlan,
        mu: MarketUnderstanding,
        ctx: ExecContext,
        state: RiskState,
        new_risk_pct: float,
    ) -> RiskDecision:
        # gate 5: kill switch — highest priority
        if state.kill_switch:
            return self._veto(plan, "RUNTIME_HALT kill switch active")

        if plan.action is Action.NO_TRADE:
            return RiskDecision(plan, vetoed=False)

        # gate 4: risk-score veto (except RiskOff/SmartDCA)
        if mu.risk_score > float(self.cfg["risk_score_veto"]) and plan.plugin not in _RISK_VETO_EXEMPT:
            return self._veto(plan, f"risk_score {mu.risk_score:.0f} > veto threshold")

        # gate 9: protections lock (§21.1)
        if state.protection_locked:
            return self._veto(plan, "protection guard locked (§21.1)")

        # gate 6: Tier-1 trading gate (§16.4)
        if not state.is_tier1:
            return self._veto(plan, "asset not Tier 1 at order time")

        # gate 7: cross-venue intersection membership (§16.1C)
        if state.is_cross_venue and not state.intersection_ok:
            return self._veto(plan, "cross-venue plan lacks intersection membership")

        # gate 3: daily stop
        if state.day_pnl_pct <= -float(self.cfg["daily_stop_pct"]):
            return self._veto(plan, "daily stop hit")

        # gate 2: max positions / per-symbol
        if state.open_positions >= int(self.cfg["max_positions"]):
            return self._veto(plan, "max positions reached")

        # gate 1: portfolio heat
        if state.open_risk_pct + new_risk_pct > float(self.cfg["max_portfolio_heat_pct"]):
            return self._veto(plan, "portfolio heat cap exceeded")

        # gate 2b: correlated bucket risk
        if state.bucket_risk_pct + new_risk_pct > float(self.cfg["max_correlated_bucket_pct"]):
            return self._veto(plan, "correlation bucket risk cap exceeded")

        # gate 10: per-asset allocation
        new_alloc = self._alloc_pct(plan, ctx)
        if state.per_asset_alloc_pct + new_alloc > float(self.cap["max_equity_pct_per_asset"]):
            return self._veto(plan, "per-asset allocation cap exceeded")

        # gate 11: per-bucket allocation
        if state.bucket_alloc_pct + new_alloc > float(self.div["max_bucket_pct"]):
            return self._veto(plan, "per-bucket allocation cap exceeded")

        # gate 12: stablecoin reserve floor
        floor = float(self.div["stablecoin_reserve_floor_pct"])
        if state.reserve_pct - new_alloc < floor:
            return self._veto(plan, "stablecoin reserve floor breached")

        return RiskDecision(plan, vetoed=False)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _alloc_pct(plan: TradePlan, ctx: ExecContext) -> float:
        if not plan.size_quote or ctx.equity_usdt <= 0:
            return 0.0
        return plan.size_quote / ctx.equity_usdt * PCT

    def _veto(self, plan: TradePlan, reason: str) -> RiskDecision:
        no_trade = TradePlan(
            plugin=plan.plugin, symbol=plan.symbol, action=Action.NO_TRADE,
            reasons=[*plan.reasons, f"VETO: {reason}"],
        )
        return RiskDecision(no_trade, vetoed=True, reason=reason)


__all__ = ["RiskDecision", "RiskManager", "RiskState"]
