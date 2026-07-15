"""Position sizer (§7.5 + §23.10A, card P4-T1).

Runs AFTER the evaluator selects a winner (§25.4). Fixed-fractional risk with
confidence scaling, then the capacity MIN chain: final size is the MINIMUM of the
risk-based size and every capacity cap (concentration, 24h-volume, book-depth,
and — when book levels are available — exit-slippage). Any binding cap is
recorded in ``TradePlan.reasons`` so you can see when liquidity, not conviction,
set the size (§23.10A). Below the exchange minimum → NO_TRADE (§25.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from aimos.core.normalize import HALF, PCT
from aimos.core.schemas import Action, ExecContext, TradePlan
from aimos.data.orderbook import simulate_market_order


@dataclass
class SizingInputs:
    """External capacity inputs the pipeline supplies (§23.10A)."""

    volume_24h_usd: Optional[float] = None
    book_depth_1pct_usd: Optional[float] = None
    exit_levels: Optional[Sequence] = None  # opposite-side book for exit sim
    mid: Optional[float] = None
    min_notional_usd: float = 0.0  # exchange minimum; pipeline passes MarketInfo value


@dataclass
class SizingResult:
    size_quote: Optional[float]
    reasons: list[str]
    rejected: bool = False


class PositionSizer:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg  # params.execution subtree
        self.base_risk_pct = float(cfg["base_risk_pct"])
        lo, hi = cfg["confidence_scale_range"]
        self.scale_lo, self.scale_hi = float(lo), float(hi)
        self.scale_pivot = float(cfg["confidence_scale_pivot"])

    def size(
        self, plan: TradePlan, ctx: ExecContext, inputs: SizingInputs
    ) -> SizingResult:
        if plan.action is Action.NO_TRADE or not plan.entry or plan.stop_loss is None:
            return SizingResult(None, ["no geometry to size"], rejected=True)

        frac_risk = abs(plan.entry - plan.stop_loss) / plan.entry
        if frac_risk <= 0:
            return SizingResult(None, ["degenerate stop"], rejected=True)

        conf_scale = self._clamp(plan.confidence / self.scale_pivot, self.scale_lo, self.scale_hi)
        risk_quote = ctx.equity_usdt * (self.base_risk_pct / PCT) * conf_scale
        risk_size = risk_quote / frac_risk

        caps = ctx.caps
        reasons: list[str] = []
        candidates: list[tuple[str, float]] = [("risk", risk_size)]

        # concentration cap (net of existing same-asset exposure)
        existing = sum(
            p.qty * p.entry for p in ctx.open_positions if p.symbol == plan.symbol
        )
        equity_cap = ctx.equity_usdt * (caps.max_equity_pct_per_asset / PCT) - existing
        candidates.append(("concentration", max(equity_cap, 0.0)))

        # 24h volume cap
        if inputs.volume_24h_usd is not None:
            candidates.append(("volume", inputs.volume_24h_usd * (caps.max_pct_of_24h_volume / PCT)))

        # book depth cap
        if inputs.book_depth_1pct_usd is not None:
            candidates.append(("depth", inputs.book_depth_1pct_usd * (caps.max_pct_of_book_depth / PCT)))

        # exit-slippage cap (simulate full exit; shrink until it clears)
        exit_capped = self._exit_slippage_cap(risk_size, inputs, caps)
        if exit_capped is not None:
            candidates.append(("exit_slippage", exit_capped))

        binding, final = min(candidates, key=lambda kv: kv[1])
        if binding != "risk":
            pct_cut = (1.0 - final / risk_size) * PCT if risk_size > 0 else 0.0
            reasons.append(f"size cut {pct_cut:.0f}% by {binding} cap")

        if final < inputs.min_notional_usd:
            return SizingResult(None, reasons + ["size below minimum after caps"], rejected=True)

        plan.size_quote = final
        plan.reasons.extend(reasons)
        return SizingResult(final, reasons)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    def _exit_slippage_cap(self, risk_size, inputs, caps) -> Optional[float]:
        """Largest size whose full-exit slippage clears ``max_exit_slippage_bps``."""
        if inputs.exit_levels is None or inputs.mid is None:
            return None
        size = risk_size
        # coarse shrink: halve until full-exit slippage clears the cap (robust)
        for _ in range(32):  # noqa: magic — iteration bound, not a tunable
            slip = simulate_market_order(inputs.exit_levels, size, inputs.mid)
            if slip <= caps.max_exit_slippage_bps:
                return size
            size *= HALF
        return size  # smallest tried


__all__ = ["PositionSizer", "SizingInputs", "SizingResult"]
