"""Recorded-dataset integrity tests (§4, §16.4 — card P1-T6 DoD)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from aimos.data.candles import CandleStore, gap_fill

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _clean_frame(n: int) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        ts = START + timedelta(hours=i)
        rows.append([int(ts.timestamp() * 1000), price, price + 2, price - 1, price + 1, 10.0])
        price += 1
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.drop(columns=["ts_ms"])
    return gap_fill(df, "1h")


def _run_integrity(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dataset_integrity.py"), str(root)],
        capture_output=True, text=True,
    )


def test_integrity_passes_on_clean_dataset(tmp_path):
    store = CandleStore(tmp_path)
    store.write("binance", "BTC/USDT", "1h", _clean_frame(48))
    r = _run_integrity(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_integrity_detects_gap(tmp_path):
    df = _clean_frame(48)
    df = df.drop(df.index[20])  # punch a hole → gap on the grid
    store = CandleStore(tmp_path)
    # write directly to bypass the store's own sort/dedup (still gappy)
    path = store.path_for("binance", "BTC/USDT", "1h")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)

    r = _run_integrity(tmp_path)
    assert r.returncode == 1
    assert "gap" in r.stdout.lower()


def test_integrity_detects_duplicates(tmp_path):
    df = _clean_frame(10)
    dup = pd.concat([df, df.iloc[[5]]])  # duplicate one timestamp
    store = CandleStore(tmp_path)
    path = store.path_for("binance", "ETH/USDT", "1h")
    path.parent.mkdir(parents=True, exist_ok=True)
    dup.to_parquet(path)

    r = _run_integrity(tmp_path)
    assert r.returncode == 1
    assert "duplicate" in r.stdout.lower()
