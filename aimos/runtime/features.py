"""Runtime feature toggles (UI + Telegram). Safe flags only; live/funded LOCKED.

Flips the keyless/data-driven flags at runtime (no restart) and rebuilds the
orchestrator's engines + plugins so the change takes effect on the next tick.
Dangerous flags (live trading, mandate, funded multi-venue execution) are LOCKED
here and refuse to flip — those stay behind the §23.8 go-live ladder + funded,
withdrawal-disabled keys, never a dashboard button. Not in the linted layers.
"""

from __future__ import annotations

from typing import Any, Callable

# runtime-toggleable, safe (keyless / no funds at risk)
TOGGLEABLE = ("scalp", "cross_exchange")
# refuse to flip from UI/Telegram — require the go-live ladder + capital
LOCKED = {
    "live": "live trading — requires the §23.8 go-live ladder + funded keys",
    "mode": "live mode — requires the §23.8 go-live ladder",
    "mandate": "the live-trading mandate — set in mandate.yaml after the ladder",
    "multi_venue_live": "funded cross-venue execution — needs balances + keys (Phase D)",
    "market_making": "market making — needs ≥ $5k live capital",
}


class FeatureController:
    """Applies safe runtime flag flips and rebuilds the orchestrator."""

    def __init__(self, params: Any, rebuild: Callable[[], None]) -> None:
        self.params = params
        self._rebuild = rebuild

    def snapshot(self) -> dict:
        f = self.params.features.model_dump()
        return {
            "features": {
                "scalp": bool(f.get("scalp_enabled")),
                "cross_exchange": bool(f.get("cross_exchange_enabled")),
                "telegram": bool(f.get("telegram_enabled")),
                "llm_news_sensor": bool(f.get("llm_news_sensor")),
                "live_data": bool(f.get("live_data")),
            },
            "toggleable": list(TOGGLEABLE),
            "locked": LOCKED,
        }

    def set(self, name: str, value: bool) -> dict:
        name = (name or "").strip().lower()
        value = bool(value)
        if name in LOCKED:
            return {"ok": False, "error": f"'{name}' is LOCKED — {LOCKED[name]} (not a toggle)"}
        if name not in TOGGLEABLE:
            return {"ok": False,
                    "error": f"'{name}' is not runtime-toggleable. Toggleable: {list(TOGGLEABLE)}"}
        if name == "scalp":
            self.params.features.scalp_enabled = value
        elif name == "cross_exchange":
            self.params.features.cross_exchange_enabled = value
            arb = self.params.plugins.get("cross_exchange_arb")
            if arb is not None:
                arb.enabled = value  # single toggle also (dis)arms the P8 plugin
        self._rebuild()
        return {"ok": True, "feature": name, "enabled": value}


__all__ = ["FeatureController", "LOCKED", "TOGGLEABLE"]
