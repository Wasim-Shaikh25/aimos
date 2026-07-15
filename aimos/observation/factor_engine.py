"""Factor engine — Observation Module 14 (§20.1, card P5-T6).

Cross-sectional by nature: computes each active alpha across the T1+T2 panel,
z-scores the asset within the panel, and emits ``factor_<alpha_id>`` evidence
(direction = sign(z × IC_sign)). Uses the vendored VT factor math. The IC
selection job (``learning/factor_select``) chooses which alphas are active and
writes ``config/factors_active.yaml``.

All tunables (z_cap, reliability, active alphas) from config (§23.12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from aimos.core.normalize import z_to_strength
from aimos.core.schemas import Direction, Evidence, Timeframe
from vendor.vt_factors import alpha_momentum, cross_sectional_zscore


class FactorEngine:
    def __init__(self, obs_cfg: Mapping[str, Any], factors_cfg: Mapping[str, Any], reliability: float) -> None:
        self.z_cap = float(obs_cfg["normalization"]["z_cap"])
        self.active = factors_cfg.get("alphas", []) or []
        self.reliability = reliability

    def emit(self, panel: Mapping[str, Sequence[float]], now: datetime) -> dict[str, list[Evidence]]:
        """panel: base → close series. Returns base → factor evidence list."""
        out: dict[str, list[Evidence]] = {base: [] for base in panel}
        for alpha in self.active:
            alpha_id = alpha["id"]
            ic_sign = int(alpha.get("ic_sign", 1))
            lookback = int(alpha.get("lookback", 1))
            values, bases = self._alpha_values(panel, lookback)
            if len(values) < 2:
                continue
            zs = cross_sectional_zscore(values)
            for base, z in zip(bases, zs):
                direction = Direction.BULLISH if z * ic_sign > 0 else (
                    Direction.BEARISH if z * ic_sign < 0 else Direction.NEUTRAL)
                out[base].append(Evidence(
                    source=f"factor_engine.{alpha_id}", symbol=base, timeframe=Timeframe.H1,
                    timestamp=now, name=f"factor_{alpha_id}", value=float(z),
                    direction=direction, strength=z_to_strength(float(z), self.z_cap),
                    reliability=self.reliability, meta={"alpha": alpha_id, "ic_sign": ic_sign},
                ))
        return out

    @staticmethod
    def _alpha_values(panel, lookback) -> tuple[list[float], list[str]]:
        values: list[float] = []
        bases: list[str] = []
        for base, closes in panel.items():
            if len(closes) > lookback:
                values.append(alpha_momentum(closes, lookback))
                bases.append(base)
        return values, bases


__all__ = ["FactorEngine"]
