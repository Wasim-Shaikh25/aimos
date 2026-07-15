"""Observation engine base + shared helpers (§5.0, card P2-T1).

Every Layer-1 engine subclasses ``ObservationEngine`` and returns ``Evidence``
only — never a buy/sell signal (§0 rule 1). Engines:

* receive their config subtree (``EngineConfig``) and a ``Clock`` (§5.0),
* read the ``MarketContext`` (candles per timeframe, book window, funding, …),
* return ``[]`` when data is insufficient — never raise for missing optional
  feeds (per-engine isolation keeps the pipeline degrading gracefully, §10.1),
* own all recency predicates internally (§25.3) — Layer 2 never inspects candles.

Normalization (``z_to_strength`` / ``ratio_to_strength``) and TA math live in
``aimos.core`` so the magic-number lint governs only decision-path *tunables*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import pandas as pd

from aimos.core.clock import Clock
from aimos.core.normalize import HALF, clamp01, ratio_to_strength, z_to_strength
from aimos.core.schemas import Evidence, MarketContext

EngineConfig = Mapping[str, Any]  # the engine's subtree of the Params tree (§25.1)


class ObservationEngine(ABC):
    """Abstract base for all 13 observation engines (§5.0)."""

    name: str = "observation_engine"

    def __init__(self, cfg: EngineConfig, clock: Clock, reliability: float = HALF) -> None:
        self.cfg = cfg
        self.clock = clock
        self.reliability = reliability

    @abstractmethod
    def observe(self, ctx: MarketContext) -> list[Evidence]:
        """Return evidence for this tick; ``[]`` when data is insufficient."""

    # -- helpers shared by subclasses ---------------------------------------

    def _z_strength(self, z: float) -> float:
        return z_to_strength(z, float(self.cfg["normalization"]["z_cap"]))

    def _ratio_strength(self, ratio: float) -> float:
        norm = self.cfg["normalization"]
        return ratio_to_strength(ratio, float(norm["ratio_neutral"]), float(norm["ratio_cap"]))

    @staticmethod
    def _clamp01(x: float) -> float:
        return clamp01(x)


def real_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Drop synthetic (gap-filled) candles — volume math must skip them (§4.1, §5.2)."""
    if "synthetic" in df.columns:
        return df[~df["synthetic"].astype(bool)]
    return df


__all__ = ["EngineConfig", "ObservationEngine", "real_candles"]
