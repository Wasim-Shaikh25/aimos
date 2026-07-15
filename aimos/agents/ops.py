"""A3 Ops agent (§18.3, card P6-T4).

Online, BOUNDED remediation. Allowed actions are exactly the enum below; anything
else escalates to a human. This is the audit boundary proving the agent stayed
inside its allowlist. Not in the linted layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OpsAction(str, Enum):
    RESTART_CONNECTOR = "restart_connector"
    SWITCH_FEED_SECONDARY = "switch_feed_secondary"
    RERUN_DISCOVERY = "rerun_discovery"
    OPEN_INCIDENT_THREAD = "open_incident_thread"


@dataclass
class OpsResult:
    action: str
    allowed: bool
    outcome: str


class OpsAgent:
    name = "agent:ops"

    def execute(self, action: str, detail: Optional[dict] = None) -> OpsResult:
        try:
            OpsAction(action)
        except ValueError:
            return OpsResult(action, allowed=False, outcome="escalated to human (not in allowlist)")
        return OpsResult(action, allowed=True, outcome=f"executed {action}")


__all__ = ["OpsAction", "OpsAgent", "OpsResult"]
