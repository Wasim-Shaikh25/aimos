"""Dataset downloader helpers (no network)."""

from __future__ import annotations

import io
import zipfile

from scripts.download_history import _binance_pair, _month_range, _read_zip_csv, _to_timeframe


def test_binance_pair_and_timeframe():
    assert _binance_pair("BTC/USDT") == "BTCUSDT"
    assert _to_timeframe("H1") == "1h"
    assert _to_timeframe("M15") == "15m"


def test_month_range():
    pairs = _month_range(3)
    assert len(pairs) == 3
    # Months should be strictly increasing chronologically.
    assert all((pairs[i][0], pairs[i][1]) < (pairs[i + 1][0], pairs[i + 1][1]) for i in range(len(pairs) - 1))


def test_read_zip_csv_parses_klines():
    rows = []
    start = 1704067200000000  # microseconds
    for i in range(3):
        rows.append(
            f"{start + i * 3600000000},{100.0 + i},{101.0 + i},{99.0 + i},{100.5 + i},{10.0 + i},"
            f"{start + (i + 1) * 3600000000},0.0,1,0.0,0.0,0.0"
        )
    csv = "\n".join(rows).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-1h.csv", csv)
    df = _read_zip_csv(buf.getvalue())
    assert len(df) == 3
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[0] == 100.5
