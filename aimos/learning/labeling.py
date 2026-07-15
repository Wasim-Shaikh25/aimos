"""Triple-barrier labeling for ML training (§8.2, card P4-T5).

Label every decision (traded or not): +1 if the upper barrier (+upper×ATR) is
hit before the lower (−lower×ATR); 0 if the lower is hit first; ``None`` (drop)
if the time barrier expires with |move| < noise×ATR (§8.2). Thresholds from
``config`` (learning.triple_barrier). Not in the magic-number-linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class BarrierConfig:
    upper_atr: float = 1.5
    lower_atr: float = 1.5
    noise_atr: float = 0.3


def triple_barrier_label(
    decision_price: float,
    atr: float,
    future_prices: Sequence[float],
    cfg: BarrierConfig,
    long: bool = True,
) -> Optional[int]:
    """Return 1 (upper first), 0 (lower first), or None (timeout in noise band).

    ``future_prices`` are the prices within the horizon (time barrier = its end).
    For a long: upper = +upper×ATR, lower = −lower×ATR. Mirrored for a short.
    """
    if atr <= 0 or not future_prices:
        return None
    upper = decision_price + cfg.upper_atr * atr
    lower = decision_price - cfg.lower_atr * atr
    for p in future_prices:
        if p >= upper:
            return 1 if long else 0
        if p <= lower:
            return 0 if long else 1
    # time barrier hit: drop if the net move is within the noise band
    final_move = abs(future_prices[-1] - decision_price)
    if final_move < cfg.noise_atr * atr:
        return None
    # otherwise label by direction of the (small) net move
    up = future_prices[-1] > decision_price
    return (1 if up else 0) if long else (0 if up else 1)


__all__ = ["BarrierConfig", "triple_barrier_label"]
