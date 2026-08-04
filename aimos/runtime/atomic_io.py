"""Atomic JSON persistence for runtime state files (audit finding M8).

A plain ``open("w")``/``write_text`` truncates the target *before* writing, so a
process killed mid-write (watchdog restart, OOM, ``docker stop`` during a rolling
deploy) leaves a truncated, unparseable file. Writing to a sibling temp file and
``os.replace``-ing it into place is atomic on POSIX: readers see either the old
file or the new one, never a torn one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Serialize ``obj`` to ``path`` atomically (temp file + fsync + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on POSIX; keeps temp on same filesystem
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


__all__ = ["atomic_write_json"]
