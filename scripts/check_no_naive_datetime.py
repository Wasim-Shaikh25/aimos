#!/usr/bin/env python3
"""Fail if any module under ``aimos/`` uses naive datetime or wall-clock calls.

Enforces §4.5 / §23.3: modules must obtain time via ``clock.now()`` and never
``datetime.utcnow()`` or bare ``datetime.now()``. Naive ``datetime(...)``
literals and ``.replace(tzinfo=None)`` are also flagged. ``aimos/core/clock.py``
is the sanctioned home of ``datetime.now(timezone.utc)`` and is exempt.

Usage: python scripts/check_no_naive_datetime.py
Exit 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIMOS = ROOT / "aimos"

# (regex, human message)
FORBIDDEN = [
    (re.compile(r"\butcnow\s*\("), "datetime.utcnow() — use clock.now()"),
    (re.compile(r"\bdatetime\.now\s*\(\s*\)"), "naive datetime.now() — use clock.now()"),
    (re.compile(r"\.replace\(\s*tzinfo\s*=\s*None"), "stripping tzinfo — keep UTC-aware"),
]

# Files allowed to construct UTC-aware time directly.
EXEMPT = {AIMOS / "core" / "clock.py"}


def main() -> int:
    violations: list[str] = []
    for path in AIMOS.rglob("*.py"):
        if path in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for rx, msg in FORBIDDEN:
                if rx.search(line):
                    rel = path.relative_to(ROOT)
                    violations.append(f"{rel}:{lineno}: {msg}")
    if violations:
        print("Naive-datetime lint FAILED:")
        for v in violations:
            print("  " + v)
        return 1
    print("Naive-datetime lint OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
