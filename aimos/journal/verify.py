"""Journal hash-chain verifier CLI (§24.5, card P4-T5).

Usage: python -m aimos.journal.verify <journal.sqlite>
Exit 0 = chain intact, 1 = tampering detected.
"""

from __future__ import annotations

import sys

from aimos.journal.journal import Journal


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m aimos.journal.verify <journal.sqlite>")
        return 2
    j = Journal(argv[0])
    ok, broken = j.verify()
    j.close()
    if ok:
        print("Journal hash chain OK — no tampering detected.")
        return 0
    print(f"Journal TAMPERING DETECTED at row_hash {broken}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
