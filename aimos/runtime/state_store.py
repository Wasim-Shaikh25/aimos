"""Runtime state persistence for the serve loop.

Keeps equity curve, balances, positions, feature flags, go-live ladder, and
the latest monitor report across restarts. Uses a JSON file by default
(``state/tenants/<org_id>/state.json``) and the tenant DB when SaaS is enabled.
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


class ControlStore:
    """Lightweight cross-process control channel for the API/loop split.

    The API process writes operator controls (halt, pause, feature toggles); the
    loop process reads them at the start of each tick. Stored as JSON beside the
    runtime state for file-backed deployments and in the tenant DB for SaaS.
    """

    def __init__(self, org_id: str = "local", state_dir: Path | None = None) -> None:
        self.org_id = org_id
        self.saas_enabled = get_saas_config().enabled
        self._noop = state_dir is None and not self.saas_enabled
        self._path = (state_dir or (Path("state") / "tenants" / org_id)) / "control.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if self._noop:
            return {}
        if self.saas_enabled:
            return _db_load(self.org_id).get("controls", {})
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError) as exc:
            log.warning("control_load_failed", path=str(self._path), error=str(exc))
            return {}

    def save(self, controls: dict[str, Any]) -> None:
        if self._noop:
            return
        controls = controls.copy()
        controls["updated_at"] = _now()
        if self.saas_enabled:
            _db_save(self.org_id, controls=controls)
            return
        atomic_write_json(self._path, controls)


class RuntimeStateStore:
    """Save/load the runtime ``holder`` snapshot."""

    def __init__(self, org_id: str = "local", state_dir: Path | None = None) -> None:
        self.org_id = org_id
        self.saas_enabled = get_saas_config().enabled
        self._noop = state_dir is None and not self.saas_enabled
        self.file_path = (state_dir or (Path("state") / "tenants" / org_id)) / "state.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        """Load the most recently persisted state."""
        if self._noop:
            return {}
        if self.saas_enabled:
            return _db_load(self.org_id)
        if self.file_path.exists():
            try:
                with self.file_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError) as exc:
                # A torn write from an unclean shutdown must not crash boot
                # (audit finding M8) — start fresh rather than fail closed on read.
                log.warning("runtime_state_unreadable", path=str(self.file_path), error=str(exc))
                return {}
        return {}

    def save(self, snapshot: dict[str, Any]) -> None:
        """Persist a snapshot dict."""
        if self._noop:
            return
        snapshot = snapshot.copy()
        snapshot["updated_at"] = _now()
        if self.saas_enabled:
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
            return
        atomic_write_json(self.file_path, snapshot)


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
