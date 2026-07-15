#!/usr/bin/env python3
"""GPL tripwire reminder (§21.1, §22.3 rule 5).

Prints a reminder whenever ``vendor/GPL_TRIPWIRE.md`` lists any GPL-origin files.
This is informational (always exit 0) for a PRIVATE project — GPL obligations
trigger only on distribution. It exists so the obligation is never forgotten:
before any distribution, every listed file must be clean-room rewritten.

Usage: python scripts/check_gpl_tripwire.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIPWIRE = ROOT / "vendor" / "GPL_TRIPWIRE.md"


def main() -> int:
    if not TRIPWIRE.exists():
        print("No GPL_TRIPWIRE.md — nothing to remind about.")
        return 0
    rows = [
        line
        for line in TRIPWIRE.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\|\s*`", line.strip())  # table rows referencing a file
    ]
    if rows:
        print(f"⚠️  GPL TRIPWIRE: {len(rows)} GPL-origin file(s) tracked.")
        print("    Private use is fine; REWRITE these clean-room before ANY distribution:")
        for r in rows:
            cell = r.split("|")[1].strip()
            print(f"      - {cell}")
    else:
        print("GPL tripwire list is empty — no distribution blockers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
