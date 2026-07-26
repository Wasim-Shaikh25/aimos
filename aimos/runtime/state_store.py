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

from aimos.saas.settings import get_saas_config
from aimos.saas.state_tenant import load_state as _db_load, save_state as _db_save


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
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
                ladder=snapshot.get("ladder"),
                features=snapshot.get("features"),
            )
            return
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, default=str)


def build_snapshot(holder: dict[str, Any], broker: Any, sim: Any, ladder: Any) -> dict[str, Any]:
    """Build a serializable snapshot from the serve loop internals."""
    return {
        "broker": broker.state_dict() if hasattr(broker, "state_dict") else {},
        "sim": sim.state_dict() if sim and hasattr(sim, "state_dict") else {},
        "equity": holder.get("equity") or [],
        "ladder": ladder.status() if ladder else {},
        "features": holder.get("features") or {},
        "monitor": holder.get("monitor") or {},
    }
