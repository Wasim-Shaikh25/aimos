"""Execution plugin registry (§7.1).

``build_plugins`` constructs the enabled core plugins (P1–P5) from Params; each
reads its own ``config/plugins/<name>.yaml`` subtree. The evaluator needs no
changes to accommodate new plugins — adding one is a new file + config entry.
"""

from __future__ import annotations

from typing import Any

from aimos.execution.base_plugin import ExecutionPlugin
from aimos.execution.plugins.breakout import Breakout
from aimos.execution.plugins.mean_reversion import MeanReversion
from aimos.execution.plugins.pullback import Pullback
from aimos.execution.plugins.risk_off import RiskOff
from aimos.execution.plugins.trend_following import TrendFollowing

# plugin class → config/plugins/<key>.yaml
_CORE: list[tuple[type[ExecutionPlugin], str]] = [
    (RiskOff, "risk_off"),
    (TrendFollowing, "trend_following"),
    (Pullback, "pullback"),
    (Breakout, "breakout"),
    (MeanReversion, "mean_reversion"),
]


def build_plugins(params: Any) -> list[ExecutionPlugin]:
    """Enabled core plugins, RiskOff always first (§7.2)."""
    plugin_cfgs = params.plugins  # dict[str, _Loose]
    out: list[ExecutionPlugin] = []
    for cls, key in _CORE:
        raw = plugin_cfgs.get(key)
        cfg = raw.model_dump() if hasattr(raw, "model_dump") else (raw or {})
        if cfg.get("enabled", True):
            out.append(cls(cfg))
    return out


__all__ = [
    "Breakout",
    "MeanReversion",
    "Pullback",
    "RiskOff",
    "TrendFollowing",
    "build_plugins",
]
