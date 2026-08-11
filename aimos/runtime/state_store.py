"""Runtime state persistence for the serve loop.

Keeps equity curve, balances, positions, feature flags, go-live ladder, and
controls across restarts. Uses a JSON file by default
(``state/tenants/<org_id>/state.json``). When ``storage.database_url`` is set,
everything moves into the same PostgreSQL/SQLite database so a server restart or
migration is just a connection-string change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from aimos.runtime.atomic_io import atomic_write_json
from aimos.saas.settings import get_saas_config
from aimos.saas.state_tenant import load_state as _db_load, save_state as _db_save

log = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class _NoopBackend:
    def load(self) -> dict[str, Any]:
        return {}

    def save(self, _payload: dict[str, Any]) -> None:
        return None


class _FileBackend:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                return dict(json.load(f))
        except (ValueError, OSError) as exc:
            log.warning("state_load_failed", path=str(self.file_path), error=str(exc))
            return {}

    def save(self, snapshot: dict[str, Any]) -> None:
        atomic_write_json(self.file_path, snapshot)


class _SaaSBackend:
    def __init__(self, org_id: str) -> None:
        self.org_id = org_id

    def load(self) -> dict[str, Any]:
        return _db_load(self.org_id)

    def save(self, snapshot: dict[str, Any]) -> None:
        _db_save(
            self.org_id,
            broker_state=snapshot.get("broker"),
            sim_state=snapshot.get("sim"),
            equity=snapshot.get("equity"),
            balances=snapshot.get("balances"),
            positions=snapshot.get("positions"),
            ladder=snapshot.get("ladder"),
            features=snapshot.get("features"),
            view=snapshot.get("view"),
            controls=snapshot.get("controls"),
        )


class _SqlBackend:
    def __init__(self, org_id: str, database_url: str) -> None:
        self.org_id = org_id
        self.database_url = database_url
        from aimos.storage.db import get_storage_engine, RuntimeStateRecord

        self.engine = get_storage_engine(database_url)
        self._record_cls = RuntimeStateRecord

    def load(self) -> dict[str, Any]:
        from sqlalchemy.orm import Session

        with Session(self.engine) as session:
            row = session.get(self._record_cls, self.org_id)
            return row.state if row is not None else {}

    def save(self, snapshot: dict[str, Any]) -> None:
        from sqlalchemy.orm import Session

        with Session(self.engine) as session:
            row = session.get(self._record_cls, self.org_id)
            if row is None:
                row = self._record_cls(organization_id=self.org_id, state=snapshot)
                session.add(row)
            else:
                row.state = snapshot
            session.commit()


class _FileControlBackend:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as f:
                return dict(json.load(f))
        except (ValueError, OSError) as exc:
            log.warning("control_load_failed", path=str(self._path), error=str(exc))
            return {}

    def save(self, controls: dict[str, Any]) -> None:
        atomic_write_json(self._path, controls)


class _SaaSControlBackend:
    def __init__(self, org_id: str) -> None:
        self.org_id = org_id

    def load(self) -> dict[str, Any]:
        return _db_load(self.org_id).get("controls", {})

    def save(self, controls: dict[str, Any]) -> None:
        _db_save(self.org_id, controls=controls)


class _SqlControlBackend:
    def __init__(self, org_id: str, database_url: str) -> None:
        self.org_id = org_id
        self.database_url = database_url
        from aimos.storage.db import ControlStateRecord, get_storage_engine

        self.engine = get_storage_engine(database_url)
        self._record_cls = ControlStateRecord

    def load(self) -> dict[str, Any]:
        from sqlalchemy.orm import Session

        with Session(self.engine) as session:
            row = session.get(self._record_cls, self.org_id)
            return row.controls if row is not None else {}

    def save(self, controls: dict[str, Any]) -> None:
        from sqlalchemy.orm import Session

        with Session(self.engine) as session:
            row = session.get(self._record_cls, self.org_id)
            if row is None:
                row = self._record_cls(organization_id=self.org_id, controls=controls)
                session.add(row)
            else:
                row.controls = controls
            session.commit()


# ---------------------------------------------------------------------------
# Public stores
# ---------------------------------------------------------------------------

class ControlStore:
    """Cross-process control channel (halt, pause, toggles)."""

    def __init__(
        self,
        org_id: str = "local",
        state_dir: Path | None = None,
        database_url: str = "",
    ) -> None:
        self.org_id = org_id
        if database_url:
            self._backend: Any = _SqlControlBackend(org_id, database_url)
        elif get_saas_config().enabled:
            self._backend = _SaaSControlBackend(org_id)
        elif state_dir is not None:
            self._backend = _FileControlBackend(
                (state_dir or (Path("state") / "tenants" / org_id)) / "control.json"
            )
        else:
            self._backend = _NoopBackend()

    def load(self) -> dict[str, Any]:
        return self._backend.load()

    def save(self, controls: dict[str, Any]) -> None:
        controls = controls.copy()
        controls["updated_at"] = _now()
        self._backend.save(controls)


class RuntimeStateStore:
    """Save/load the runtime ``holder`` snapshot."""

    def __init__(
        self,
        org_id: str = "local",
        state_dir: Path | None = None,
        database_url: str = "",
    ) -> None:
        self.org_id = org_id
        self.file_path: Path | None = None
        if database_url:
            self._backend: Any = _SqlBackend(org_id, database_url)
        elif get_saas_config().enabled:
            self._backend = _SaaSBackend(org_id)
        elif state_dir is not None:
            file_path = (state_dir or (Path("state") / "tenants" / org_id)) / "state.json"
            self._backend = _FileBackend(file_path)
            self.file_path = file_path
        else:
            self._backend = _NoopBackend()

    def load(self) -> dict[str, Any]:
        """Load the most recently persisted state."""
        return self._backend.load()

    def save(self, snapshot: dict[str, Any]) -> None:
        """Persist a snapshot dict."""
        snapshot = snapshot.copy()
        snapshot["updated_at"] = _now()
        self._backend.save(snapshot)


def build_snapshot(
    holder: dict[str, Any],
    broker: Any,
    sim: Any,
    ladder: Any,
    view: dict[str, Any] | None = None,
    controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable snapshot from the serve loop internals."""
    broker_state = broker.state_dict() if hasattr(broker, "state_dict") else {}
    positions = broker_state.get("positions") if isinstance(broker_state, dict) else []
    balances: dict[str, Any] = {}
    if sim and hasattr(sim, "state_dict"):
        sim_state = sim.state_dict()
        balances = sim_state.get("balances", {})
    else:
        sim_state = {}
    return {
        "broker": broker_state,
        "sim": sim_state,
        "equity": holder.get("equity") or [],
        "balances": balances,
        "positions": positions or [],
        "ladder": ladder.status() if ladder else {},
        "features": holder.get("features") or {},
        "monitor": holder.get("monitor") or {},
        "view": view or {},
        "controls": controls or {},
    }


__all__ = ["ControlStore", "RuntimeStateStore", "build_snapshot"]
