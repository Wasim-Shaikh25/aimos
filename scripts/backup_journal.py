#!/usr/bin/env python3
"""CLI wrapper for the verified journal backup routine (§23.5, audit finding H4).

Usage:
    python scripts/backup_journal.py [--src state/aimos.sqlite]
                                     [--dest backups] [--keep 14]

Exit 0 = a verified backup was written; non-zero = failure (e.g. the fresh
backup did not verify).  Schedule it (cron / the APScheduler runtime / a compose
timer) at your target RPO.  The auth DB (``state/auth.sqlite`` or Postgres) and
``state/.settings_key`` are separate concerns — see specs/OPERATIONS.md.
"""

from __future__ import annotations

import argparse
import sys

from aimos.journal.backup import backup_journal


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verified backup of the journal (§23.5).")
    ap.add_argument("--src", default="state/aimos.sqlite")
    ap.add_argument("--dest", default="backups")
    ap.add_argument("--keep", type=int, default=14, help="timestamped snapshots to retain")
    args = ap.parse_args(argv)
    try:
        out = backup_journal(args.src, args.dest, args.keep)
    except FileNotFoundError as exc:
        print(f"backup skipped: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"backup FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"backup OK: {out} (verified) -> {args.dest}/journal-latest.sqlite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
