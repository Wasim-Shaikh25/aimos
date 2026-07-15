# Adapted from hummingbot/hummingbot (Apache-2.0) — Avellaneda–Stoikov math.
# Reference implementation (clean-room from Avellaneda & Stoikov, 2008,
# "High-frequency trading in a limit order book"). Replace with the pinned
# upstream port at vendoring time and record the SHA in vendor/VENDOR.md (§22.2B).
"""Avellaneda–Stoikov market-making math for plugin P9 (§21.2).

Pure, deterministic formulas — no state, no I/O — so they preserve AIMOS replay
guarantees. Inventory-skew and quoting live in the plugin (§21.2); this is the
core reservation-price / optimal-spread math only.
"""

from __future__ import annotations

import math


def reservation_price(
    mid: float, inventory: float, gamma: float, sigma: float, time_to_horizon: float
) -> float:
    """Inventory-adjusted reservation price.

    r = s − q·γ·σ²·(T−t). Positive inventory (long) skews the quote DOWN to
    encourage selling; negative skews UP. (Avellaneda–Stoikov eq. for r.)
    """
    return mid - inventory * gamma * (sigma ** 2) * time_to_horizon


def optimal_spread(gamma: float, sigma: float, time_to_horizon: float, k: float) -> float:
    """Optimal total bid-ask spread around the reservation price.

    δ = γ·σ²·(T−t) + (2/γ)·ln(1 + γ/k).
    """
    if gamma <= 0 or k <= 0:
        raise ValueError("gamma and k must be positive")
    return gamma * (sigma ** 2) * time_to_horizon + (2.0 / gamma) * math.log(1.0 + gamma / k)


def quote_prices(
    mid: float,
    inventory: float,
    gamma: float,
    sigma: float,
    time_to_horizon: float,
    k: float,
) -> tuple[float, float]:
    """Return (bid, ask) around the reservation price at the optimal spread."""
    r = reservation_price(mid, inventory, gamma, sigma, time_to_horizon)
    half = optimal_spread(gamma, sigma, time_to_horizon, k) / 2.0
    return r - half, r + half


__all__ = ["optimal_spread", "quote_prices", "reservation_price"]
