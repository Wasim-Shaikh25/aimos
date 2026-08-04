"""Journal backup + restore drill (§23.5, audit finding H4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from aimos.journal.backup import backup_journal
from aimos.journal.journal import Journal


def _populate(path: Path, n: int = 5) -> None:
    j = Journal(path)
    for i in range(n):
        # _append writes a hash-chain-valid row without building full records.
        j._append("decisions", f"d{i}", "SOL", "2026-07-30T00:00:00+00:00",
                  {"understanding": {}, "chosen": {}, "candidates": [], "i": i})
    j.close()


def test_backup_creates_verifiable_copy(tmp_path):
    src = tmp_path / "aimos.sqlite"
    _populate(src)
    out = backup_journal(str(src), str(tmp_path / "backups"), keep=14)
    assert out.exists()
    # The backup's own hash chain verifies.
    j = Journal(out)
    ok, broken = j.verify()
    j.close()
    assert ok is True and broken is None
    # The latest-pointer exists and also verifies.
    latest = tmp_path / "backups" / "journal-latest.sqlite"
    assert latest.exists()
    jl = Journal(latest)
    assert jl.verify()[0] is True
    jl.close()


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_journal(str(tmp_path / "nope.sqlite"), str(tmp_path / "backups"))


def test_backup_retention_prunes_oldest(tmp_path):
    src = tmp_path / "aimos.sqlite"
    _populate(src)
    dest = tmp_path / "backups"
    # Force several distinct snapshots with an explicit timestamped name each.
    import aimos.journal.backup as bj
    stamps = ["20260101T000001Z", "20260101T000002Z", "20260101T000003Z"]
    it = iter(stamps)
    original = bj._stamp
    bj._stamp = lambda: next(it)  # type: ignore[assignment]
    try:
        for _ in stamps:
            backup_journal(str(src), str(dest), keep=2)
    finally:
        bj._stamp = original
    snaps = sorted(p.name for p in dest.glob("journal-*.sqlite")
                   if p.name != "journal-latest.sqlite")
    assert len(snaps) == 2  # oldest pruned
    assert "journal-20260101T000001Z.sqlite" not in snaps


def test_restore_drill_fails_without_backup_journal(tmp_path):
    res = subprocess.run(
        ["bash", "scripts/restore_drill.sh", str(tmp_path / "missing.sqlite")],
        capture_output=True, text=True,
    )
    assert res.returncode == 1  # a drill with no backup is not a pass


def test_restore_drill_passes_with_verified_backup_journal(tmp_path):
    src = tmp_path / "aimos.sqlite"
    _populate(src)
    out = backup_journal(str(src), str(tmp_path / "backups"), keep=14)
    res = subprocess.run(
        ["bash", "scripts/restore_drill.sh", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "PASSED" in res.stdout
