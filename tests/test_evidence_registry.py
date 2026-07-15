"""Evidence-name registry tests (§25.6 — card P0-T3 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aimos.core.evidence_registry import (
    EVIDENCE_NAMES,
    DirectionSemantics,
    UnregisteredEvidenceName,
    feature_index,
    is_registered,
    require_registered,
    semantics,
)
from aimos.core.schemas import Direction, Evidence, Timeframe

TS = datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_registry_has_expected_scale():
    # Spec says ~55 names harvested from §5/§19/§21.3/§23.11.
    assert 50 <= len(EVIDENCE_NAMES) <= 70


def test_registry_names_unique():
    assert len(EVIDENCE_NAMES) == len(set(EVIDENCE_NAMES))


def test_known_names_registered():
    for name in ["volume_spike", "bos", "headline_shock", "liquidation_cascade", "ignition"]:
        assert is_registered(name)


def test_factor_family_prefix():
    assert is_registered("factor_alpha101_12")
    assert semantics("factor_alpha101_12") is DirectionSemantics.DIRECTIONAL


def test_require_registered_raises_on_unknown():
    with pytest.raises(UnregisteredEvidenceName):
        require_registered("totally_made_up_signal")


def test_evidence_rejects_unregistered_name():
    with pytest.raises(Exception):  # pydantic wraps the ValueError
        Evidence(
            source="x", symbol="BTC", timeframe=Timeframe.M5, timestamp=TS,
            name="not_a_real_evidence", value=1.0, direction=Direction.BULLISH,
            strength=0.5,
        )


def test_evidence_accepts_registered_name():
    ev = Evidence(
        source="x", symbol="BTC", timeframe=Timeframe.M5, timestamp=TS,
        name="volume_spike", value=1.0, direction=Direction.BULLISH, strength=0.5,
    )
    assert ev.name == "volume_spike"


def test_feature_index_stable_and_dense():
    idx = feature_index()
    assert idx["structure_trend"] == 0  # first registered name
    assert sorted(idx.values()) == list(range(len(EVIDENCE_NAMES)))
