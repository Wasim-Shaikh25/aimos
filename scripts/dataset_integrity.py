#!/usr/bin/env python3
"""Recorded-dataset integrity check (§4, §16.4 — card P1-T6 DoD).

Walks a data root of candle parquet files and asserts, per file:
  * the index is timezone-aware UTC and monotonic,
  * there are no duplicate timestamps,
  * the grid is gapless at the file's timeframe (synthetic bars fill real gaps),
  * required OHLCV columns are present.

The timeframe is inferred from the filename stem (``1h.parquet`` → ``1h``).

Usage: python scripts/dataset_integrity.py [data_root]
Exit 0 = all files pass, 1 = any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aimos.data.candles import OHLCV_COLUMNS, _TF_RULE  # noqa: E402


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    tf = path.stem
    if tf not in _TF_RULE:
        return [f"{path}: unknown timeframe stem {tf!r}"]

    df = pd.read_parquet(path)
    idx = df.index

    if not isinstance(idx, pd.DatetimeIndex) or idx.tz is None:
        problems.append(f"{path}: index is not timezone-aware UTC")
        return problems
    if str(idx.tz) not in ("UTC", "utc"):
        problems.append(f"{path}: index tz is {idx.tz}, expected UTC")
    if not idx.is_monotonic_increasing:
        problems.append(f"{path}: index not sorted ascending")
    if idx.has_duplicates:
        problems.append(f"{path}: duplicate timestamps present")

    missing_cols = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing_cols:
        problems.append(f"{path}: missing columns {missing_cols}")

    if len(df) > 1 and not problems:
        expected = pd.date_range(idx.min(), idx.max(), freq=_TF_RULE[tf], tz="UTC")
        if len(expected) != len(df):
            problems.append(
                f"{path}: gap detected — {len(df)} rows vs {len(expected)} expected on grid"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    data_root = Path(argv[0]) if argv else ROOT / "data"
    files = sorted(data_root.rglob("*.parquet"))
    if not files:
        print(f"No parquet files under {data_root} (nothing to check).")
        return 0

    all_problems: list[str] = []
    for f in files:
        all_problems.extend(check_file(f))

    if all_problems:
        print("Dataset integrity FAILED:")
        for p in all_problems:
            print("  " + p)
        return 1
    print(f"Dataset integrity OK — {len(files)} file(s) gapless, UTC, deduped.")
    return 0


if __name__ == "__main__":
    # Flush and os._exit avoids a rare pyarrow/pandas C++ terminate-on-shutdown
    # that can return -6 instead of the intended exit code in subprocess tests.
    import os

    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
