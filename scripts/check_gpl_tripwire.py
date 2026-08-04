#!/usr/bin/env python3
"""GPL tripwire reminder (§21.1, §22.3 rule 5, REQ-11).

Prints a reminder whenever ``vendor/GPL_TRIPWIRE.md`` lists any GPL-origin files,
or when ``pyproject.toml`` pins a known copyleft (GPL/AGPL) package.  This is
informational (always exit 0) for a PRIVATE project — GPL obligations trigger
only on distribution. It exists so the obligation is never forgotten: before any
distribution, every listed file and every copyleft dependency must be removed or
rewritten.

Usage: python scripts/check_gpl_tripwire.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIPWIRE = ROOT / "vendor" / "GPL_TRIPWIRE.md"
PYPROJECT = ROOT / "pyproject.toml"

# Dependency pins whose upstream license is GPL/AGPL (or suspected).  The current
# concrete risk is OpenBB Platform (AGPLv3 network-use clause).  This list can be
# expanded as the dependency tree changes.
COPYLEFT_RE = re.compile(
    r"(?:^|[-_.])(openbb|gpl|agpl|gnu)(?:[-_.]|$)",
    re.IGNORECASE,
)


def _parse_dependencies() -> list[str]:
    """Return every pinned dependency string from pyproject.toml."""
    deps: list[str] = []
    if not PYPROJECT.exists():
        return deps
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps.extend(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        deps.extend(group)
    return deps


def _package_name(pin: str) -> str:
    """Strip extras/version markers to leave the canonical package name."""
    # "name[extra]==1.0; marker"  ->  "name"
    name = pin.split(";")[0].strip()
    name = re.sub(r"\[.*\]", "", name)
    name = re.split(r"[<>=!~]", name)[0].strip()
    return name


def main() -> int:
    exit_code = 0
    # ---- tracked source files ----
    if TRIPWIRE.exists():
        rows = [
            line
            for line in TRIPWIRE.read_text(encoding="utf-8").splitlines()
            if re.match(r"^\|\s*`", line.strip())  # table rows referencing a file
        ]
        if rows:
            print(f"⚠️  GPL TRIPWIRE: {len(rows)} GPL-origin source file(s) tracked.")
            print("    Private use is fine; REWRITE these clean-room before ANY distribution:")
            for r in rows:
                cell = r.split("|")[1].strip()
                print(f"      - {cell}")
            exit_code = 0  # informational, never fail CI
    else:
        print("No GPL_TRIPWIRE.md — nothing to remind about.")

    # ---- dependency pins ----
    copyleft_pins: list[str] = []
    for pin in _parse_dependencies():
        name = _package_name(pin)
        if COPYLEFT_RE.search(name):
            copyleft_pins.append(pin)
    if copyleft_pins:
        print(f"⚠️  GPL TRIPWIRE: {len(copyleft_pins)} copyleft dependency pin(s) in pyproject.toml.")
        print("    Do not import these into `aimos/`; run them as isolated out-of-process services:")
        for pin in copyleft_pins:
            print(f"      - {pin}")

    if not rows and not copyleft_pins:
        print("GPL tripwire list is empty — no distribution blockers.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
