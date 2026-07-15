"""Proposal lifecycle (§18.3-A1, §18.5, card P6-T4).

A1 proposals land in ``proposals/`` as YAML diffs + rationale. Approval writes the
diff to a STAGING file (never live config) and journals the action; applying it is
a separate human config+restart step. This is the safety boundary: no agent
mutates live config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


class ProposalStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


@dataclass
class Proposal:
    proposal_id: str
    title: str
    rationale: str
    config_diff: dict  # {dotted.key: {"current": x, "proposed": y}}
    hypothesis_id: Optional[str] = None
    evidence_runs: list[str] = field(default_factory=list)
    status: ProposalStatus = ProposalStatus.OPEN

    def to_yaml(self) -> str:
        return yaml.safe_dump({
            "proposal_id": self.proposal_id, "title": self.title,
            "rationale": self.rationale, "config_diff": self.config_diff,
            "hypothesis_id": self.hypothesis_id, "evidence_runs": self.evidence_runs,
            "status": self.status.value,
        }, sort_keys=True)


class ConfigMutationForbidden(RuntimeError):
    """Approval writes staging, never live config (§18.5)."""


def approve(proposal: Proposal, staging_dir: Path | str) -> Path:
    """Write the approved diff to a STAGING file. Refuses to touch config/."""
    d = Path(staging_dir)
    if "config" in d.parts:
        raise ConfigMutationForbidden("approval writes staging, not live config (§18.5)")
    d.mkdir(parents=True, exist_ok=True)
    proposal.status = ProposalStatus.APPROVED
    path = d / f"{proposal.proposal_id}.staged.yaml"
    path.write_text(proposal.to_yaml(), encoding="utf-8")
    return path


def reject(proposal: Proposal, reason: str) -> Proposal:
    if not reason.strip():
        raise ValueError("rejection requires a one-line reason (§18.5)")
    proposal.status = ProposalStatus.REJECTED
    return proposal


__all__ = ["ConfigMutationForbidden", "Proposal", "ProposalStatus", "approve", "reject"]
