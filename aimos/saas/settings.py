"""Typed SaaS configuration loaded from ``config/saas.yaml`` (via ``Params``).

Values are overridable via ``AIMOS__SAAS__*`` env vars and the nested keys are
exposed as pydantic models so the rest of the SaaS code is type-safe.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aimos.core.config import load_params

_STATE_DIR = Path("state")
_SECRET_FILE = _STATE_DIR / ".jwt_secret"


class SMTPConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_address: str = "noreply@aimos.local"

    @model_validator(mode="after")
    def _tls_default_port(self) -> "SMTPConfig":
        if self.use_tls and self.port == 465:
            # Common STARTTLS port is 587; 465 is SSL/TLS. We accept both.
            pass
        return self


class GoogleOAuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "/auth/google/callback"


class AppleOAuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_id: str = ""
    team_id: str = ""
    key_id: str = ""
    private_key: str = ""
    redirect_uri: str = "/auth/apple/callback"


class OAuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    google: GoogleOAuthConfig = Field(default_factory=GoogleOAuthConfig)
    apple: AppleOAuthConfig = Field(default_factory=AppleOAuthConfig)


class TwilioConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""


class VonageConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_key: str = ""
    api_secret: str = ""
    from_name: str = "AIMOS"


class SMSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    driver: str = "console"
    twilio: TwilioConfig = Field(default_factory=TwilioConfig)
    vonage: VonageConfig = Field(default_factory=VonageConfig)


class AdminConfig(BaseModel):
    """Single admin user seeded at startup.  ``password`` is hashed on first run."""

    model_config = ConfigDict(extra="allow")

    user_id: str = "admin"
    email: str = ""
    phone: str = ""
    password: str = ""


class TenantDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    allow_multiple_orgs_per_user: bool = True
    default_org_name: str = "Personal"
    journal_dir: str = "state/journals"
    state_dir: str = "state/tenants"


class SaasConfig(BaseModel):
    """Runtime SaaS configuration."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    database_url: str = ""
    jwt_secret: str = ""
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=365)
    verification_code_expire_minutes: int = Field(default=15, ge=1, le=1440)
    otp_expire_minutes: int = Field(default=10, ge=1, le=1440)
    require_email_verification: bool = True
    require_strong_password: bool = True
    smtp: SMTPConfig = Field(default_factory=SMTPConfig)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    sms: SMSConfig = Field(default_factory=SMSConfig)
    tenant: TenantDefaults = Field(default_factory=TenantDefaults)
    admin: AdminConfig = Field(default_factory=AdminConfig)

    @model_validator(mode="after")
    def _ensure_jwt_secret(self) -> "SaasConfig":
        if self.enabled and not self.jwt_secret:
            self.jwt_secret = _load_or_create_jwt_secret()
        return self

    @model_validator(mode="after")
    def _ensure_database_url(self) -> "SaasConfig":
        if not self.database_url:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite:///{_STATE_DIR / 'auth.sqlite'}"
        return self


def _load_or_create_jwt_secret() -> str:
    """Persist a single JWT secret across restarts.

    If the operator supplies ``AIMOS__SAAS__JWT_SECRET`` that value is used
    instead. The generated secret is stored in ``state/.jwt_secret`` and
    must be backed up for production multi-node deployments.
    """
    env = os.environ.get("AIMOS__SAAS__JWT_SECRET", "").strip()
    if env:
        return env
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    _SECRET_FILE.write_text(secret, encoding="utf-8")
    # Restrict read to owner in POSIX environments.
    try:
        import stat

        _SECRET_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:  # noqa: BLE001
        pass
    return secret


def _get_raw_saas() -> dict[str, Any]:
    """Fetch the SaaS subtree from the global ``Params`` tree.

    ``config/saas.yaml`` is included in the single-file config load, so env
    overrides of the form ``AIMOS__SAAS__*`` are already applied.
    """
    params = load_params()
    raw = getattr(params, "saas", None)
    return raw if isinstance(raw, dict) else {}


def get_saas_config() -> SaasConfig:
    """Return a typed, validated SaaS configuration."""
    return SaasConfig.model_validate(_get_raw_saas())
