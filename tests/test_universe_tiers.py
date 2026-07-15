"""Tier engine hysteresis tests (§16.1 D — card P15-T3 DoD)."""

from __future__ import annotations

from aimos.universe.tiers import Tier, TierChange, TierEngine


def _engine(**kw) -> TierEngine:
    defaults = dict(
        t1_max=12, t2_max=60, t1_provisional_max=3,
        promote=65.0, demote=50.0, demote_scans=3,
    )
    defaults.update(kw)
    return TierEngine(**defaults)


def test_promote_at_65():
    eng = _engine()
    eng.update({"SOL": 66.0, "BTC": 40.0})
    assert eng.tier_of("SOL") == Tier.T1
    assert eng.tier_of("BTC") == Tier.T2  # in watch ranking, not T1


def test_below_promote_does_not_enter_t1():
    eng = _engine()
    eng.update({"SOL": 64.9})
    assert eng.tier_of("SOL") != Tier.T1


def test_hysteresis_exit_requires_three_scans_below_50():
    eng = _engine()
    eng.update({"SOL": 70.0})
    assert eng.tier_of("SOL") == Tier.T1

    eng.update({"SOL": 48.0})  # 1st below
    assert eng.tier_of("SOL") == Tier.T1
    eng.update({"SOL": 45.0})  # 2nd below
    assert eng.tier_of("SOL") == Tier.T1
    eng.update({"SOL": 30.0})  # 3rd below → demote
    assert eng.tier_of("SOL") == Tier.T2


def test_streak_resets_on_recovery():
    eng = _engine()
    eng.update({"SOL": 70.0})
    eng.update({"SOL": 48.0})  # 1st below
    eng.update({"SOL": 55.0})  # recovers (>=demote) → streak reset
    eng.update({"SOL": 48.0})  # 1st below again
    eng.update({"SOL": 48.0})  # 2nd below
    assert eng.tier_of("SOL") == Tier.T1  # only 2 consecutive, not demoted


def test_t1_cap_enforced():
    eng = _engine(t1_max=2)
    scores = {f"A{i}": 90.0 - i for i in range(5)}  # 5 candidates all above promote
    eng.update(scores)
    assert len(eng.t1_members()) == 2  # cap enforced
    # the two highest scores win
    assert eng.tier_of("A0") == Tier.T1
    assert eng.tier_of("A1") == Tier.T1
    assert eng.tier_of("A2") == Tier.T2


def test_provisional_slots_reserved_and_capped():
    eng = _engine(t1_provisional_max=2)
    assert eng.add_provisional("PUMP1") is True
    assert eng.add_provisional("PUMP2") is True
    assert eng.add_provisional("PUMP3") is False  # cap
    assert eng.is_tradable("PUMP1")  # provisional counts as tradable (§7.4 r6)
    eng.clear_provisional("PUMP1")
    assert not eng.is_tradable("PUMP1")


def test_only_t1_is_tradable():
    eng = _engine()
    eng.update({"SOL": 70.0, "DOGE": 55.0})
    assert eng.is_tradable("SOL")  # T1
    assert not eng.is_tradable("DOGE")  # T2 — not tradable
    assert not eng.is_tradable("UNKNOWN")  # T3 default


def test_tier_changes_journaled():
    changes: list[TierChange] = []
    eng = TierEngine(promote=65, demote=50, demote_scans=3, on_change=changes.append)
    eng.update({"SOL": 70.0})
    assert any(c.base == "SOL" and c.new == Tier.T1 for c in changes)
