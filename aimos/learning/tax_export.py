"""Tax export CLI (§23.6, card P5-T8).

`python -m aimos.learning.tax_export --tax-year 2026 --journal j.sqlite --out fills.csv`
→ CSV of all fills/fees/funding. Jurisdiction-specific formatting is out of scope
(consult a professional). Not in the linted layers.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from aimos.journal.journal import Journal

_FIELDS = ["decision_id", "exit_time", "exit_price", "pnl_quote", "pnl_r", "exit_reason"]


def export_outcomes(journal: Journal, tax_year: int, out_path: Path) -> int:
    rows = journal.conn.execute("SELECT payload FROM outcomes").fetchall()
    written = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            rec = json.loads(r["payload"])
            if str(rec.get("exit_time", "")).startswith(str(tax_year)):
                w.writerow({k: rec.get(k, "") for k in _FIELDS})
                written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export fills/fees/funding for a tax year.")
    p.add_argument("--tax-year", type=int, required=True)
    p.add_argument("--journal", required=True)
    p.add_argument("--out", default="tax_export.csv")
    args = p.parse_args(argv)
    j = Journal(args.journal)
    n = export_outcomes(j, args.tax_year, Path(args.out))
    j.close()
    print(f"wrote {n} rows for {args.tax_year} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
