"""A2 Risk Sentinel agent (§18.3, card P6-T4).

Online, READ-ONLY, every 15 min. Produces narrative risk digests + escalations.
Its ONLY verb is *notify* — it has no method that pauses, flattens, or vetoes
(the deterministic risk manager holds those powers). Not in the linted layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ESCALATE = "escalate"


@dataclass
class RiskDigest:
    severity: Severity
    narrative: str
    snapshot: dict = field(default_factory=dict)  # the numbers it was derived from


class RiskSentinel:
    name = "agent:sentinel"

    # NOTE: there is deliberately NO pause/flatten/veto method here (§18.3).

    def digest(self, positions: list, heat_pct: float, correlations: dict) -> RiskDigest:
        sev = Severity.INFO
        note = f"{len(positions)} positions, heat {heat_pct:.1f}%"
        hi_corr = {k: v for k, v in correlations.items() if v > 0.9}
        if hi_corr:
            sev = Severity.ESCALATE
            note += f"; correlated >0.9: {sorted(hi_corr)} — effective heat elevated"
        elif heat_pct >= 1.8:
            sev = Severity.WARN
        return RiskDigest(sev, note, {"heat_pct": heat_pct, "high_corr": hi_corr})


__all__ = ["RiskDigest", "RiskSentinel", "Severity"]
