"""Feature-monitoring / self-test agent.

Runs in the background, probes every feature of the system on an interval, and
produces a coverage report (ok / degraded / failing per feature). Optionally
**forces coverage** by enabling the safe, keyless features (cross_exchange, scalp)
so every code path is exercised without waiting for organic market conditions —
so end-to-end testing happens fast. It never touches live/funded features (those
stay locked). Reports are exposed at /api/monitor and written to
``state/monitor_report.json``. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass
class FeatureCheck:
    name: str
    status: str   # "ok" | "degraded" | "failing"
    detail: str = ""


def ok(name: str, detail: str = "") -> FeatureCheck:
    return FeatureCheck(name, "ok", detail)


def degraded(name: str, detail: str = "") -> FeatureCheck:
    return FeatureCheck(name, "degraded", detail)


def failing(name: str, detail: str = "") -> FeatureCheck:
    return FeatureCheck(name, "failing", detail)


class FeatureMonitorAgent:
    """Runs a dict of probes and aggregates a coverage report."""

    def __init__(self, probes: dict[str, Callable[[], FeatureCheck]],
                 feature_ctl=None, force_coverage: bool = False) -> None:
        self.probes = probes
        self.feature_ctl = feature_ctl
        self.force_coverage_flag = force_coverage
        self.report: dict = {"features": [], "summary": {}, "coverage_pct": 0.0}
        self._forced = False

    def force_coverage(self) -> None:
        """Enable the safe features so their paths get exercised (once)."""
        if self.force_coverage_flag and self.feature_ctl and not self._forced:
            for feature in ("cross_exchange", "scalp"):
                try:
                    self.feature_ctl.set(feature, True)
                except Exception:  # noqa: BLE001
                    log.exception("monitor_force_failed", feature=feature)
            self._forced = True

    def run_once(self) -> dict:
        checks: list[FeatureCheck] = []
        for name, probe in self.probes.items():
            try:
                checks.append(probe())
            except Exception as exc:  # noqa: BLE001 — a probe error is itself a finding
                checks.append(failing(name, f"probe error: {exc}"))
        n_ok = sum(c.status == "ok" for c in checks)
        n_deg = sum(c.status == "degraded" for c in checks)
        n_fail = sum(c.status == "failing" for c in checks)
        total = len(checks) or 1
        self.report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "coverage_pct": round(100.0 * n_ok / total, 1),
            "features": [asdict(c) for c in checks],
            "summary": {"ok": n_ok, "degraded": n_deg, "failing": n_fail, "total": len(checks)},
            "forced": self._forced,
        }
        return self.report


__all__ = ["FeatureCheck", "FeatureMonitorAgent", "degraded", "failing", "ok"]
