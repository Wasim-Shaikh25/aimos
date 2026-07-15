"""Cost model — fees, slippage, funding (§9.2, §23.9, card P4-T6).

Not in the magic-number-linted layers, but all defaults come from
``config/costs.yaml``. Slippage: ``base + k·(order_size/depth)·100`` (§9.2).
Funding for perps is folded into trade EV (§23.9B): a position collecting funding
gets an EV credit, correctly favoring the carry side.
"""

from __future__ import annotations

from dataclasses import dataclass

_FUNDING_WINDOW_MINUTES = 480.0  # 8h funding interval (§23.9B denominator)
_PCT_TO_BPS = 100.0


@dataclass
class CostModel:
    taker_bps: float
    maker_bps: float
    slip_base_bps: float
    slip_k: float

    def slippage_bps(self, order_size_usd: float, depth_usd: float) -> float:
        """slip = base + k·(size/depth)·100 (§9.2). Empty depth → base only."""
        if depth_usd <= 0:
            return self.slip_base_bps
        return self.slip_base_bps + self.slip_k * (order_size_usd / depth_usd) * _PCT_TO_BPS

    def round_trip_fee_bps(self, taker: bool = True) -> float:
        fee = self.taker_bps if taker else self.maker_bps
        return fee * 2.0


def funding_cost_bps(
    funding_rate_bps: float, hold_minutes: float, direction_sign: int
) -> float:
    """Projected funding cost in bps (§23.9B).

    ``= rate_bps × (hold / 480) × sign``. ``sign`` = +1 long, −1 short. Positive
    when paying (long + positive funding), negative (a credit) when receiving.
    """
    return funding_rate_bps * (hold_minutes / _FUNDING_WINDOW_MINUTES) * direction_sign


def total_forward_costs_bps(
    model: CostModel,
    order_size_usd: float,
    depth_usd: float,
    taker: bool = True,
    funding_rate_bps: float = 0.0,
    hold_minutes: float = 0.0,
    direction_sign: int = 1,
) -> float:
    """Round-trip fee + entry/exit slippage + projected funding (§23.9)."""
    slip = model.slippage_bps(order_size_usd, depth_usd) * 2.0  # entry + exit
    fee = model.round_trip_fee_bps(taker=taker)
    funding = funding_cost_bps(funding_rate_bps, hold_minutes, direction_sign)
    return fee + slip + funding


def from_config(costs_cfg: dict) -> CostModel:
    return CostModel(
        taker_bps=float(costs_cfg["taker_bps"]),
        maker_bps=float(costs_cfg["maker_bps"]),
        slip_base_bps=float(costs_cfg["slip_base_bps"]),
        slip_k=float(costs_cfg["slip_k"]),
    )


__all__ = ["CostModel", "from_config", "funding_cost_bps", "total_forward_costs_bps"]
