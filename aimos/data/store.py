"""Parquet/DB read-write layer (§2, §4).

Phase 1 is parquet-backed (candles) with the journal on SQLite later (§8.1).
This module centralises the on-disk layout and re-exports ``CandleStore`` so
callers depend on one storage entry point. TimescaleDB/Postgres migration
(Phase 2+) swaps the implementation behind these helpers.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from aimos.data.candles import CandleStore

DEFAULT_DATA_ROOT = Path("data")


def dataset_files(root: Path | str) -> list[Path]:
    """All candle parquet files under a data root."""
    return sorted(Path(root).rglob("*.parquet"))


def load_parquet(path: Path | str) -> pd.DataFrame:
    return pd.read_parquet(path)


__all__ = ["CandleStore", "DEFAULT_DATA_ROOT", "dataset_files", "load_parquet"]
