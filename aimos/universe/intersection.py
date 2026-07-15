"""Cross-exchange availability matrix (§16.1 C, card P15-T2).

Built after each discovery from the ``Registry``. ``common(min_venues)`` answers
the "only deal with what's available across platforms" requirement: cross-venue
plugins (arb, lead-lag) require membership here on BOTH legs; single-venue
plugins do not shrink to the intersection (§16.1 C binding rules).
"""

from __future__ import annotations

from aimos.universe.registry import Registry


def build_matrix(registry: Registry) -> dict[str, dict[str, bool]]:
    """``matrix[base][venue] = tradable?`` over all known bases (§16.1 C).

    Includes inactive/suspended (base, venue) cells as ``False`` so the UI
    heat-grid (§16.2 Screen 4) shows every listing, tradable or not.
    """
    matrix: dict[str, dict[str, bool]] = {}
    for base in registry.bases():
        tradable = set(registry.venues(base))
        matrix[base] = {v: (v in tradable) for v in _known_venues(registry, base)}
    return matrix


def _known_venues(registry: Registry, base: str) -> list[str]:
    return list(registry._by_base.get(base.upper(), {}).keys())


def common(registry: Registry, min_venues: int = 2) -> set[str]:
    """Bases tradable on ≥ ``min_venues`` venues (active, non-suspended)."""
    return {base for base in registry.bases() if len(registry.venues(base)) >= min_venues}


__all__ = ["build_matrix", "common"]
