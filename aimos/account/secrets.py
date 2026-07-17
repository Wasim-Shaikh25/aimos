"""Per-venue API credential loading (Phase D §2.3). File > env; never logged.

Precedence: a secrets file named by ``AIMOS_SECRETS_FILE`` (or config
``secrets.file``) wins, then per-venue env vars ``AIMOS_KEY_<VENUE>`` /
``AIMOS_SECRET_<VENUE>``. Secrets are never logged, journaled, or sent to the UI —
the UI only ever sees a boolean "connected" and the venue name. Not in the
magic-number-linted layers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def load_secrets(secrets_file: str = "", venues: Optional[list[str]] = None) -> dict:
    """Return ``{venue_lower: {"apiKey", "secret", "withdraw"}}`` for venues that
    have credentials. Missing venues are simply absent (no error)."""
    creds: dict[str, dict] = {}
    path = secrets_file or os.environ.get("AIMOS_SECRETS_FILE", "")
    if path and Path(path).exists():
        import yaml  # optional; only needed when a file is configured
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        block = data.get("venues", data)
        if isinstance(block, dict):
            for venue, c in block.items():
                if isinstance(c, dict) and c.get("apiKey"):
                    creds[str(venue).lower()] = {
                        "apiKey": c["apiKey"], "secret": c.get("secret", ""),
                        "withdraw": bool(c.get("withdraw", False)),
                    }
    for venue in venues or []:
        vl = venue.lower()
        if vl in creds:
            continue
        key = os.environ.get(f"AIMOS_KEY_{venue.upper()}")
        sec = os.environ.get(f"AIMOS_SECRET_{venue.upper()}")
        if key and sec:
            creds[vl] = {"apiKey": key, "secret": sec, "withdraw": False}
    return creds


def has_secret(creds: dict, venue: str) -> bool:
    return venue.lower() in creds


__all__ = ["has_secret", "load_secrets"]
