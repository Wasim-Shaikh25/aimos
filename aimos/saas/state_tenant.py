"""Per-tenant runtime state persistence in the auth/tenant database.

Only active when SaaS is enabled. For single-user mode the file-based store in
``aimos/runtime/state_store.py`` is used instead.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aimos.saas.db import get_session_maker
from aimos.saas.models import OrganizationState


def _session() -> Session:
    return get_session_maker()()


def load_state(org_id: str) -> dict[str, Any]:
    """Return the saved runtime state for an organization, or an empty dict."""
    with _session() as session:
        row = session.get(OrganizationState, org_id)
        if row is None:
            return {}
        return {
            "broker": row.broker_state,
            "sim": row.sim_state,
            "equity": row.equity,
            "balances": row.balances,
            "positions": row.positions,
            "ladder": row.ladder,
            "features": row.features,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def save_state(
    org_id: str,
    *,
    broker_state: dict[str, Any] | None = None,
    sim_state: dict[str, Any] | None = None,
    equity: list[float] | None = None,
    balances: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    ladder: dict[str, Any] | None = None,
    features: dict[str, Any] | None = None,
) -> None:
    """Persist runtime state for an organization."""
    with _session() as session:
        row = session.get(OrganizationState, org_id)
        if row is None:
            row = OrganizationState(organization_id=org_id)
            session.add(row)
        if broker_state is not None:
            row.broker_state = broker_state
        if sim_state is not None:
            row.sim_state = sim_state
        if equity is not None:
            row.equity = equity
        if balances is not None:
            row.balances = balances
        if positions is not None:
            row.positions = positions
        if ladder is not None:
            row.ladder = ladder
        if features is not None:
            row.features = features
        session.commit()


def delete_state(org_id: str) -> None:
    """Remove an organization's runtime state (used for resets)."""
    with _session() as session:
        row = session.get(OrganizationState, org_id)
        if row is not None:
            session.delete(row)
            session.commit()
