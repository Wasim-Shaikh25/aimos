"""Threshold optimizer — proposals only (§21.4, card P6-T2).

Optuna tunes config thresholds against nested walk-forward OOS Sharpe, but the
output is ALWAYS a proposal file, NEVER a direct config write (self-modifying
trading systems are unauditable). Optuna is an optional dep; the anti-overfit
rails + proposal emission are testable without it. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml


class ConfigWriteForbidden(RuntimeError):
    """Optimizer output must never land in config/ — only proposals/ (§21.4)."""


@dataclass
class OptimizationProposal:
    study_name: str
    objective: str
    best_params: dict
    plateau_note: str
    run_cards: list[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        return yaml.safe_dump({
            "kind": "threshold_optimization",
            "study": self.study_name,
            "objective": self.objective,
            "proposed_params": self.best_params,
            "plateau": self.plateau_note,
            "evidence_runs": self.run_cards,
        }, sort_keys=True)

    def write(self, proposals_dir: Path | str) -> Path:
        d = Path(proposals_dir)
        # hard rail: refuse to write anywhere under config/
        if "config" in d.parts:
            raise ConfigWriteForbidden("optimizer may not write into config/ (§21.4)")
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"optimize-{self.study_name}.yaml"
        path.write_text(self.to_yaml(), encoding="utf-8")
        return path


def pick_plateau(trials: list[tuple[dict, float]], tolerance_pct: float = 5.0) -> tuple[dict, str]:
    """Among trials within tolerance% of the best score, prefer a robust plateau
    pick (§21.4). ``trials`` = [(params, score)]. Returns (params, note)."""
    if not trials:
        return {}, "no trials"
    best = max(s for _, s in trials)
    band = [p for p, s in trials if s >= best * (1.0 - tolerance_pct / 100.0)]
    # the "middle" of the band is more robust than the razor-edge best
    chosen = band[len(band) // 2]
    return chosen, f"{len(band)} trials within {tolerance_pct}% of best {best:.3f}"


__all__ = ["ConfigWriteForbidden", "OptimizationProposal", "pick_plateau"]
