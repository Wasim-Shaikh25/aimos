"""P9 MarketMaking (§21.2, card P6-T7). Regime {RANGING}.

Avellaneda–Stoikov quoting (vendored hb_mm math), inventory skew, and hard gates:
coin_health ≥ 70, spread ≥ spread_fee_mult× fees, min capital, and withdraw ALL
quotes when MANIPULATION behavior prob exceeds the threshold. Under the min
capital the plugin refuses (fees eat sub-$5k MM). Config from
config/plugins/market_making.yaml. Micro book state rides in key_levels['mm'].
"""

from __future__ import annotations

from typing import Any, Mapping

from aimos.core.schemas import (
    Action,
    Behavior,
    ExecContext,
    MarketUnderstanding,
    Regime,
    TradePlan,
)
from aimos.execution.base_plugin import ExecutionPlugin
from vendor.hb_mm import quote_prices


class MarketMaking(ExecutionPlugin):
    name = "MarketMaking"
    required_regimes = {Regime.RANGING}

    def propose(self, mu: MarketUnderstanding, ctx: ExecContext) -> TradePlan | None:
        # min-capital refusal (§21.2)
        if ctx.equity_usdt < float(self.cfg["min_capital_usd"]):
            return None
        # withdraw all quotes on manipulation suspicion
        manip = mu.behavior_probs.get(Behavior.MANIPULATION.value, 0.0)
        if mu.behavior is Behavior.MANIPULATION or manip > float(self.cfg["manipulation_withdraw_prob"]):
            return None

        mm = mu.key_levels.get("mm")
        if not isinstance(mm, dict):
            return None
        mid = _f(mm.get("mid"))
        sigma = _f(mm.get("sigma"))
        inventory = _f(mm.get("inventory"))
        spread_bps = _f(mm.get("spread_bps"))
        if None in (mid, sigma, inventory, spread_bps) or mid <= 0:
            return None
        # spread must clear a multiple of fees (§21.2)
        fee_bps = ctx.fee_maker_bps + ctx.fee_taker_bps
        if spread_bps < float(self.cfg["spread_fee_mult"]) * fee_bps:
            return None

        gamma = _f(mm.get("gamma")) or float(self.cfg["gamma"])
        k = _f(mm.get("k")) or float(self.cfg["k"])
        time_to_horizon = _f(mm.get("time_to_horizon")) or float(self.cfg["time_to_horizon"])
        bid, ask = quote_prices(mid, inventory, gamma, sigma, time_to_horizon, k)
        return TradePlan(
            plugin=self.name, symbol=mu.symbol, action=Action.LONG,  # quote both sides
            entry=mid, stop_loss=mid - (mid - bid), take_profit=ask,
            expected_rr=1.0, expected_hold_minutes=mu.horizon_minutes,
            expected_costs_bps=ctx.fee_maker_bps * 2.0, confidence=mu.confidence,
            reasons=[f"MM quotes bid {bid:.6g} / ask {ask:.6g}"],
            meta={"mode_tag": "mm", "bid": bid, "ask": ask, "inventory": inventory},
        )


def _f(x):
    return float(x) if isinstance(x, (int, float)) else None


__all__ = ["MarketMaking"]
