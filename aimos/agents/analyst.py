"""A1 Research Analyst agent (§18.3, §20.3, card P6-T4).

Reads journal stats / calibration / per-plugin performance and produces written
proposals (YAML diffs + rationale + hypothesis id). Powers NONE on the live
system — proposals are human-gated (§18.3). Not in the linted layers.
"""
from __future__ import annotations

from typing import Optional

from aimos.agents.proposals import Proposal


class ResearchAnalyst:
    name = "agent:analyst"

    def propose_disable_in_regime(
        self, plugin: str, regime: str, hit_rate: float, n_trades: int,
        proposal_id: str, hypothesis_id: Optional[str] = None,
    ) -> Proposal:
        return Proposal(
            proposal_id=proposal_id,
            title=f"disable {plugin} in {regime}",
            rationale=f"{plugin} hit-rate in {regime} is {hit_rate:.0%} over {n_trades} trades",
            config_diff={f"plugins.{plugin}.disabled_regimes": {"current": [], "proposed": [regime]}},
            hypothesis_id=hypothesis_id,
        )

    def propose_reliability_change(
        self, sensor: str, decayed_to: float, proposal_id: str,
    ) -> Proposal:
        return Proposal(
            proposal_id=proposal_id,
            title=f"lower {sensor} reliability",
            rationale=f"{sensor} reliability decayed to {decayed_to:.2f}",
            config_diff={f"weights.reliability.{sensor}": {"current": None, "proposed": decayed_to}},
        )


__all__ = ["ResearchAnalyst"]
