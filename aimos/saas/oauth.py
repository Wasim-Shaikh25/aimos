"""OAuth2 helpers for Google and Apple sign-in.

Only free/open-source libraries are used. Operator supplies OAuth client
credentials in ``config/saas.yaml``.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt as pyjwt
from authlib.jose import JsonWebKey, jwt as auth_jwt

from aimos.saas.settings import get_saas_config


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _google_cfg() -> dict[str, Any]:
    return get_saas_config().oauth.google.model_dump()


def _apple_cfg() -> dict[str, Any]:
    return get_saas_config().oauth.apple.model_dump()


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


def google_authorize_url(
    state: str | None = None,
    nonce: str | None = None,
    redirect_uri: str | None = None,
) -> str:
    """Build the Google OAuth2 authorization URL."""
    cfg = _google_cfg()
    redirect_uri = redirect_uri or cfg["redirect_uri"]
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    if nonce:
        params["nonce"] = nonce
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def google_exchange_code(code: str, redirect_uri: str | None = None) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""
    cfg = _google_cfg()
    redirect_uri = redirect_uri or cfg["redirect_uri"]
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def google_verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Google ID token using Google's tokeninfo endpoint."""
    cfg = _google_cfg()
    resp = httpx.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"id_token": id_token},
        timeout=30.0,
    )
    resp.raise_for_status()
    claims = resp.json()
    if claims.get("aud") != cfg["client_id"]:
        raise ValueError("Google ID token audience mismatch")
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise ValueError("Google ID token issuer mismatch")
    return claims


# ---------------------------------------------------------------------------
# Apple
# ---------------------------------------------------------------------------


def _generate_apple_client_secret() -> str:
    """Generate the Apple client-secret JWT (ES256)."""
    cfg = _apple_cfg()
    now = _utcnow()
    payload = {
        "iss": cfg["team_id"],
        "iat": now,
        "exp": now + timedelta(hours=1),
        "aud": "https://appleid.apple.com",
        "sub": cfg["client_id"],
    }
    headers = {"alg": "ES256", "kid": cfg["key_id"]}
    private_key = cfg["private_key"]
    if not private_key:
        raise ValueError("Apple private_key is not configured")
    if "\\n" in private_key:
        private_key = private_key.encode().decode("unicode_escape")
    return pyjwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def apple_authorize_url(
    state: str | None = None,
    nonce: str | None = None,
    redirect_uri: str | None = None,
) -> str:
    """Build the Apple Sign In authorization URL."""
    cfg = _apple_cfg()
    redirect_uri = redirect_uri or cfg["redirect_uri"]
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "scope": "name email",
        "response_mode": "form_post",
    }
    if state:
        params["state"] = state
    if nonce:
        params["nonce"] = nonce
    return "https://appleid.apple.com/auth/authorize?" + urlencode(params)


def apple_exchange_code(code: str, redirect_uri: str | None = None) -> dict[str, Any]:
    """Exchange an Apple authorization code for tokens."""
    cfg = _apple_cfg()
    client_secret = _generate_apple_client_secret()
    redirect_uri = redirect_uri or cfg["redirect_uri"]
    resp = httpx.post(
        "https://appleid.apple.com/auth/token",
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _apple_jwks() -> list[dict[str, Any]]:
    resp = httpx.get("https://appleid.apple.com/auth/keys", timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("keys", [])


def apple_verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify an Apple ID token signature and claims."""
    cfg = _apple_cfg()
    header = pyjwt.get_unverified_header(id_token)
    kid = header.get("kid")
    if not kid:
        raise ValueError("Apple ID token missing kid")
    jwk = next((k for k in _apple_jwks() if k.get("kid") == kid), None)
    if jwk is None:
        raise ValueError("Apple public key not found")
    key = JsonWebKey.import_key(jwk)
    claims = auth_jwt.decode(id_token, key)
    if claims.get("aud") != cfg["client_id"]:
        raise ValueError("Apple ID token audience mismatch")
    if claims.get("iss") != "https://appleid.apple.com":
        raise ValueError("Apple ID token issuer mismatch")
    return dict(claims)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)
