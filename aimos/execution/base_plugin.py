"""Execution plugin contract (§7.1, card P4-T1).

Plugins consume ONLY ``MarketUnderstanding`` + ``ExecContext`` — never raw
candles (§0 rule 3). They define trade GEOMETRY (entry/SL/TP/rr/hold/costs/
confidence) and return ``size_quote=None``; sizing happens after selection
(§25.4). ``can_trade`` gates by regime/confidence/coin_health before ``propose``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from aimos.core.schemas import ExecContext, MarketUnderstanding, Regime, TradePlan


class ExecutionPlugin(ABC):
    name: str = "plugin"
    required_regimes: set[Regime] = set()

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        # cfg = this plugin's config subtree (config/plugins/<name>.yaml)
        self.cfg = cfg
        # RiskOff omits these and overrides can_trade; trading plugins set them
        # in config/plugins/<name>.yaml. Absent → 0 (no gate).
        self.min_confidence = float(cfg.get("min_confidence", 0))
        self.min_coin_health = float(cfg.get("min_coin_health", 0))

    def can_trade(self, mu: MarketUnderstanding) -> bool:
        if self.required_regimes and mu.regime not in self.required_regimes:
            return False
        return mu.confidence >= self.min_confidence and mu.coin_health >= self.min_coin_health

    @abstractmethod
    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        """Return a geometry-complete TradePlan (size_quote=None) or None."""

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def estimate_costs_bps(ctx: ExecContext) -> float:
        """Round-trip taker + entry/exit slippage at nominal size (§25.4).

        Uses taker fees on both legs plus the liquidity-engine slippage estimates
        already in ExecContext. Funding (§23.9B) is added by the cost model for
        perp holds; exact costs are recomputed at final size by the sizer.
        """
        return ctx.fee_taker_bps * 2.0 + ctx.slippage_entry_bps + ctx.slippage_exit_bps


__all__ = ["ExecutionPlugin"]
