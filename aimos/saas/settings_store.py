"""Single-user settings and encrypted exchange-secret store.

Replaces the per-tenant YAML workflow: the dashboard writes config overrides and
API keys here; the runtime reads them at boot and each tick.  Secrets are
encrypted at rest with a server-side Fernet key and are never returned to the UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, Session

from aimos.saas.db import Base, get_session_maker


class UserSettings(Base):
    """One row per user (single-user deployment uses user_id='default')."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secrets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SettingsStore:
    """Encrypted settings store keyed by user_id."""

    _key: bytes | None = None

    def __init__(self, user_id: str = "default") -> None:
        self.user_id = user_id

    @classmethod
    def _master_key(cls) -> bytes:
        if cls._key is not None:
            return cls._key
        path = Path("state/.settings_key")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            key = Fernet.generate_key()
            path.write_bytes(key)
            os.chmod(path, 0o600)
        cls._key = path.read_bytes()
        return cls._key

    def _fernet(self) -> Fernet:
        return Fernet(self._master_key())

    def _encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, token: str) -> str:
        return self._fernet().decrypt(token.encode("ascii")).decode("utf-8")

    def _get_or_create(self, session: Session) -> UserSettings:
        row = session.get(UserSettings, self.user_id)
        if row is None:
            row = UserSettings(user_id=self.user_id, config={}, secrets={})
            session.add(row)
        return row

    def get_config(self) -> dict[str, Any]:
        with get_session_maker()() as session:
            row = session.get(UserSettings, self.user_id)
            return dict(row.config) if row else {}

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        import copy
        with get_session_maker()() as session:
            row = self._get_or_create(session)
            cfg = copy.deepcopy(row.config) if row.config else {}
            self._deep_update(cfg, updates)
            row.config = cfg
            session.commit()
            return dict(row.config)

    def set_exchange(self, venue: str, data: dict[str, Any]) -> None:
        """Write exchange credentials. ``apiKey``/``secret`` are encrypted."""
        encrypted: dict[str, Any] = {}
        for k, v in data.items():
            if k in ("apiKey", "secret") and isinstance(v, str):
                encrypted[k] = self._encrypt(v)
            else:
                encrypted[k] = v
        with get_session_maker()() as session:
            row = self._get_or_create(session)
            secrets = dict(row.secrets)
            secrets[venue] = encrypted
            row.secrets = secrets
            session.commit()

    def delete_exchange(self, venue: str) -> bool:
        with get_session_maker()() as session:
            row = session.get(UserSettings, self.user_id)
            if row is None:
                return False
            secrets = dict(row.secrets)
            removed = secrets.pop(venue, None) is not None
            row.secrets = secrets
            session.commit()
            return removed

    def get_exchanges(self) -> dict[str, dict[str, Any]]:
        """Return metadata for each configured exchange (no keys)."""
        with get_session_maker()() as session:
            row = session.get(UserSettings, self.user_id)
            if row is None:
                return {}
            out: dict[str, dict[str, Any]] = {}
            for venue, data in row.secrets.items():
                meta = {k: v for k, v in data.items() if k not in ("apiKey", "secret")}
                meta["has_key"] = bool(data.get("apiKey"))
                meta["has_secret"] = bool(data.get("secret"))
                out[venue] = meta
            return out

    def get_exchange_credentials(self, venue: str) -> dict[str, Any] | None:
        """Return plaintext credentials for one exchange (runtime use only)."""
        with get_session_maker()() as session:
            row = session.get(UserSettings, self.user_id)
            if row is None:
                return None
            data = row.secrets.get(venue)
            if not data:
                return None
            out = dict(data)
            for k in ("apiKey", "secret"):
                if k in out and isinstance(out[k], str):
                    try:
                        out[k] = self._decrypt(out[k])
                    except Exception:
                        pass  # fallback to stored value if not encrypted
            return out

    @staticmethod
    def _deep_update(base: dict[str, Any], overlay: dict[str, Any]) -> None:
        for key, value in overlay.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                SettingsStore._deep_update(base[key], value)
            else:
                base[key] = value
