"""Single-user settings and encrypted exchange-secret store.

Replaces the per-tenant YAML workflow: the dashboard writes config overrides and
API keys here; the runtime reads them at boot and each tick. Secrets are
encrypted at rest with a server-side Fernet key and are never returned to the UI.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from aimos.storage.db import UserSettingsRecord, get_storage_engine, normalize_sqlalchemy_url


def _secrets_dir() -> Path:
    """Secrets live outside ``dashboard/dist``'s ancestry by default.

    Override with ``AIMOS_SECRETS_DIR``; otherwise ``~/.aimos/secrets``.
    """
    env = os.environ.get("AIMOS_SECRETS_DIR", "")
    if env:
        return Path(env)
    return Path.home() / ".aimos" / "secrets"


def _settings_key_file() -> Path:
    """Resolved at call time so tests can point ``AIMOS_SECRETS_DIR`` at a temp dir."""
    return _secrets_dir() / ".settings_key"


def _settings_database_url() -> str:
    """Use the unified operational database when configured, otherwise a local SQLite file."""
    from aimos.core.config import load_params

    params = load_params()
    storage_cfg = params.model_dump().get("storage", {}) or {}
    database_url = storage_cfg.get("database_url", "")
    if database_url:
        return normalize_sqlalchemy_url(database_url)
    _STATE_DIR = Path("state")
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{_STATE_DIR / 'settings.sqlite'}"


class SettingsStore:
    """Encrypted settings store for the single local user."""

    _key: bytes | None = None

    def __init__(self, user_id: str = "default", database_url: str = "") -> None:
        self.user_id = user_id
        url = database_url or _settings_database_url()
        self.engine = get_storage_engine(url)

    @classmethod
    def _master_key(cls) -> bytes:
        if cls._key is not None:
            return cls._key
        path = _settings_key_file()
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

    def _get_or_create(self, session: Session) -> UserSettingsRecord:
        row = session.get(UserSettingsRecord, self.user_id)
        if row is None:
            row = UserSettingsRecord(user_id=self.user_id, config={}, secrets={})
            session.add(row)
        return row

    def get_config(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(UserSettingsRecord, self.user_id)
            return dict(row.config) if row else {}

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = self._get_or_create(session)
            cfg = copy.deepcopy(row.config) if row.config else {}
            self._deep_update(cfg, updates)
            row.config = cfg
            session.commit()
            return dict(row.config)

    def set_exchange(self, venue: str, data: dict[str, Any]) -> None:
        """Write exchange credentials. ``apiKey``/``secret`` are encrypted.
        Venue and exchange_id are normalized to lowercase so all read paths agree."""
        venue = venue.lower()
        normalized = dict(data)
        normalized.pop("venue", None)
        normalized["exchange_id"] = str(normalized.get("exchange_id") or venue).lower()
        encrypted: dict[str, Any] = {}
        for k, v in normalized.items():
            if k in ("apiKey", "secret") and isinstance(v, str):
                encrypted[k] = self._encrypt(v)
            else:
                encrypted[k] = v
        with Session(self.engine) as session:
            row = self._get_or_create(session)
            secrets = dict(row.secrets)
            secrets[venue] = encrypted
            row.secrets = secrets
            session.commit()

    def delete_exchange(self, venue: str) -> bool:
        venue = venue.lower()
        with Session(self.engine) as session:
            row = session.get(UserSettingsRecord, self.user_id)
            if row is None:
                return False
            secrets = dict(row.secrets)
            removed = secrets.pop(venue, None) is not None
            row.secrets = secrets
            session.commit()
            return removed

    def get_exchanges(self) -> dict[str, dict[str, Any]]:
        """Return metadata for each configured exchange (no keys)."""
        with Session(self.engine) as session:
            row = session.get(UserSettingsRecord, self.user_id)
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
        venue = venue.lower()
        with Session(self.engine) as session:
            row = session.get(UserSettingsRecord, self.user_id)
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
