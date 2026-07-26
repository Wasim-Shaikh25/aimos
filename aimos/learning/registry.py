"""Model registry for ML artifacts: promotion/demotion audit trail (§24.6, §8.3).

Tracks every training run, its validation AUC, Brier score, and status
(candidate/shadow/promoted/demoted). The registry is append-only and JSON-backed
so operators can diff model risk across training sessions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ModelEntry:
    path: str
    val_auc: float
    brier: float
    n_features: int
    n_samples: int
    timestamp: str = field(default_factory=_now)
    shadow_weeks_held: int = 0
    status: str = "candidate"  # candidate | shadow | promoted | demoted
    note: str = ""


class ModelRegistry:
    def __init__(self, path: Path | str = "state/model_registry.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")

    def add(self, entry: ModelEntry) -> None:
        entries = self._load()
        entries.append(asdict(entry))
        self._save(entries)

    def latest(self, status: str | None = None) -> ModelEntry | None:
        entries = self._load()
        if status:
            entries = [e for e in entries if e.get("status") == status]
        if not entries:
            return None
        raw = entries[-1]
        return ModelEntry(**raw)

    def promote(self, path: str, note: str = "") -> None:
        """Mark the most recent entry matching ``path`` as promoted."""
        entries = self._load()
        for e in reversed(entries):
            if e["path"] == path:
                e["status"] = "promoted"
                e["note"] = note or e.get("note", "")
                self._save(entries)
                return

    def demote(self, path: str, reason: str = "") -> None:
        """Mark the most recent entry matching ``path`` as demoted."""
        entries = self._load()
        for e in reversed(entries):
            if e["path"] == path:
                e["status"] = "demoted"
                e["note"] = reason or e.get("note", "")
                self._save(entries)
                return

    def check_drift(
        self,
        current_brier: float,
        previous_brier: float,
        path: str,
        threshold: float = 0.20,
    ) -> dict[str, Any]:
        """Return a demotion recommendation if Brier degraded by more than threshold."""
        degraded = previous_brier > 0 and (
            (current_brier - previous_brier) / previous_brier > threshold
        )
        if degraded:
            self.demote(path, reason=f"Brier degraded {current_brier:.4f} vs {previous_brier:.4f}")
        return {
            "degraded": degraded,
            "current_brier": current_brier,
            "previous_brier": previous_brier,
            "path": path,
        }
