"""Per-tenant journal path helper.

When SaaS is enabled, each organization gets its own journal at
``state/journals/<org_id>.sqlite``. In single-user mode the configured
``paper.journal_path`` is used unchanged.
"""

from __future__ import annotations

from pathlib import Path

from aimos.core.config import Params
from aimos.saas.settings import get_saas_config


def tenant_journal_path(org_id: str | None, params: Params) -> str:
    """Return the journal path for an organization.

    ``org_id`` is None or "local" for the single-user fallback.
    """
    if org_id and org_id != "local" and get_saas_config().enabled:
        base = Path(get_saas_config().tenant.journal_dir)
        base.mkdir(parents=True, exist_ok=True)
        return str(base / f"{org_id}.sqlite")
    paper = params.paper.model_dump() if hasattr(params.paper, "model_dump") else dict(params.paper)
    return paper.get("journal_path") or ":memory:"
