"""Model registry for ML artifacts: promotion/demotion audit trail (§24.6, §8.3).

Tracks every training run, its validation AUC, Brier score, and status
(candidate/shadow/promoted/demoted). The registry is append-only and JSON-backed
so operators can diff model risk across training sessions.

When ``storage.database_url`` is configured the registry is kept in the same
operational database; otherwise it falls back to the JSON file.
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
    def __init__(
        self,
        path: Path | str = "state/model_registry.json",
        database_url: str = "",
        org_id: str = "local",
    ) -> None:
        self.org_id = org_id
        self.database_url = database_url or ""
        self.path = Path(path)
        if not self.database_url:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if self.database_url:
            return self._load_db()
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, entries: list[dict[str, Any]]) -> None:
        if self.database_url:
            # DB writes are row-level; use _save_db when needed.
            self._save_db(entries)
            return
        self.path.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")

    def _load_db(self) -> list[dict[str, Any]]:
        from aimos.storage.db import ModelRegistryRecord, get_storage_engine
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        engine = get_storage_engine(self.database_url)
        with Session(engine) as session:
            rows = session.execute(
                select(ModelRegistryRecord.entry)
                .where(ModelRegistryRecord.organization_id == self.org_id)
                .order_by(ModelRegistryRecord.id)
            ).scalars().all()
        return [dict(row) for row in rows]

    def _save_db(self, entries: list[dict[str, Any]]) -> None:
        from aimos.storage.db import ModelRegistryRecord, get_storage_engine
        from sqlalchemy import delete
        from sqlalchemy.orm import Session

        engine = get_storage_engine(self.database_url)
        with Session(engine) as session:
            session.execute(
                delete(ModelRegistryRecord).where(ModelRegistryRecord.organization_id == self.org_id)
            )
            for entry in entries:
                session.add(
                    ModelRegistryRecord(organization_id=self.org_id, entry=entry)
                )
            session.commit()

    def add(self, entry: ModelEntry) -> None:
        if self.database_url:
            from aimos.storage.db import ModelRegistryRecord, get_storage_engine
            from sqlalchemy.orm import Session

            engine = get_storage_engine(self.database_url)
            with Session(engine) as session:
                session.add(
                    ModelRegistryRecord(organization_id=self.org_id, entry=asdict(entry))
                )
                session.commit()
            return
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
        if self.database_url:
            self._update_status(path, "promoted", note)
            return
        entries = self._load()
        for e in reversed(entries):
            if e["path"] == path:
                e["status"] = "promoted"
                e["note"] = note or e.get("note", "")
                self._save(entries)
                return

    def demote(self, path: str, reason: str = "") -> None:
        """Mark the most recent entry matching ``path`` as demoted."""
        if self.database_url:
            self._update_status(path, "demoted", reason)
            return
        entries = self._load()
        for e in reversed(entries):
            if e["path"] == path:
                e["status"] = "demoted"
                e["note"] = reason or e.get("note", "")
                self._save(entries)
                return

    def _update_status(self, path: str, status: str, note: str) -> None:
        from aimos.storage.db import ModelRegistryRecord, get_storage_engine
        from sqlalchemy import select, update
        from sqlalchemy.orm import Session

        engine = get_storage_engine(self.database_url)
        with Session(engine) as session:
            rows = session.execute(
                select(ModelRegistryRecord.id, ModelRegistryRecord.entry)
                .where(ModelRegistryRecord.organization_id == self.org_id)
                .order_by(ModelRegistryRecord.id.desc())
            ).all()
            matched = next(
                ((row.id, dict(row.entry)) for row in rows if dict(row.entry).get("path") == path),
                None,
            )
            if matched is None:
                return
            entry_id, entry = matched
            entry["status"] = status
            entry["note"] = note or entry.get("note", "")
            session.execute(
                update(ModelRegistryRecord)
                .where(ModelRegistryRecord.id == entry_id)
                .values(entry=entry)
            )
            session.commit()

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
