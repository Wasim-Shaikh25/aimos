"""Consistent, verified backup of the hash-chained journal (§23.5, audit finding H4).

A plain file copy of a live SQLite database in WAL mode can be torn; SQLite's
online backup API produces a consistent point-in-time snapshot even under
concurrent writes. Each backup's hash chain is verified immediately after it is
written — a backup that does not verify is not a backup — and an atomically
updated ``journal-latest.sqlite`` pointer is what ``restore_drill.sh`` checks.
A retention count prunes the oldest timestamped snapshots.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import timezone
from pathlib import Path

from aimos.core.clock import LiveClock
from aimos.journal.journal import Journal


def _stamp() -> str:
    return LiveClock().now().strftime("%Y%m%dT%H%M%SZ")


def _online_backup(src: Path, dest: Path) -> None:
    """Consistent snapshot of ``src`` into ``dest`` via the SQLite backup API."""
    with sqlite3.connect(str(src)) as s, sqlite3.connect(str(dest)) as d:
        s.backup(d)


def _atomic_replace_pointer(latest: Path, verified: Path) -> None:
    """Point ``journal-latest.sqlite`` at the freshly verified snapshot atomically."""
    fd, tmp = tempfile.mkstemp(dir=str(latest.parent), prefix=".latest.", suffix=".sqlite")
    os.close(fd)
    try:
        _online_backup(verified, Path(tmp))  # copy so latest is a real file, not a link
        os.replace(tmp, latest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _prune(dest: Path, keep: int) -> list[str]:
    """Keep the newest ``keep`` timestamped snapshots; delete older ones."""
    snaps = sorted(dest.glob("journal-*.sqlite"))
    snaps = [p for p in snaps if p.name != "journal-latest.sqlite"]
    removed: list[str] = []
    for p in snaps[:-keep] if keep > 0 else []:
        p.unlink()
        removed.append(p.name)
    return removed


def backup_journal(src: str = "state/aimos.sqlite", dest_dir: str = "backups", keep: int = 14) -> Path:
    """Create a verified backup; return its path. Raises on verify failure."""
    if "://" in src:
        raise ValueError(f"backup_journal does not support database URLs: {src}")
    src_path = Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"journal not found at {src_path}")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    out = dest / f"journal-{_stamp()}.sqlite"
    _online_backup(src_path, out)

    # A backup that does not verify is worse than no backup — fail loudly.
    j = Journal(out)
    ok, broken = j.verify()
    j.close()
    if not ok:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"fresh backup failed hash-chain verify at row {broken}")

    _atomic_replace_pointer(dest / "journal-latest.sqlite", out)
    _prune(dest, keep)
    return out
