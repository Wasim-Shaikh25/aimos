"""TimescaleDB time-series store (optional).

Writes operational time-series — equity, per-tick decisions, per-venue prices,
and executed trades — to TimescaleDB hypertables for analytics/dashboards at
scale. Enabled only when a DSN is configured (``storage.timescale_dsn`` or the
``AIMOS_TIMESCALE_DSN`` env var) AND ``psycopg`` is installed; otherwise it is a
safe no-op and the SHA-256 hash-chained **journal on SQLite stays the system of
record**. Writes never raise into the trading loop. Not in the linted layers.

    pip install -e '.[timescale]'
    AIMOS_TIMESCALE_DSN=postgresql://aimos:aimos@postgres:5432/aimos
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_DDL = (
    "CREATE TABLE IF NOT EXISTS equity_ts (ts timestamptz NOT NULL, equity double precision)",
    "CREATE TABLE IF NOT EXISTS decision_ts (ts timestamptz NOT NULL, symbol text, venue text,"
    " regime text, p_up double precision, action text, plugin text)",
    "CREATE TABLE IF NOT EXISTS price_ts (ts timestamptz NOT NULL, base text, venue text,"
    " mid double precision, dislocation_bps double precision)",
    "CREATE TABLE IF NOT EXISTS trade_ts (ts timestamptz NOT NULL, kind text, symbol text,"
    " strategy text, venue text, pnl_usd double precision)",
)
_HYPERTABLES = ("equity_ts", "decision_ts", "price_ts", "trade_ts")


class TimescaleStore:
    """Best-effort TimescaleDB writer. ``enabled`` is False (no-op) unless a DSN +
    psycopg are available."""

    def __init__(self, dsn: str = "") -> None:
        self.dsn = dsn or os.environ.get("AIMOS_TIMESCALE_DSN", "")
        self._conn = None
        self.enabled = False
        if self.dsn:
            self._connect()

    def _connect(self) -> None:
        try:
            import psycopg  # optional — pip install '.[timescale]'
            self._conn = psycopg.connect(self.dsn, autocommit=True)
            cur = self._conn.cursor()
            for ddl in _DDL:
                cur.execute(ddl)
            for t in _HYPERTABLES:  # promote to hypertables if this is really TimescaleDB
                try:
                    cur.execute(f"SELECT create_hypertable('{t}', 'ts', if_not_exists => TRUE)")
                except Exception:  # noqa: BLE001 — plain Postgres → keep the plain table
                    pass
            self.enabled = True
            log.info("timescale_connected", tables=len(_HYPERTABLES))
        except Exception:  # noqa: BLE001 — no psycopg / DB down → stay a no-op
            log.warning("timescale_unavailable",
                        hint="pip install '.[timescale]' and set AIMOS_TIMESCALE_DSN")
            self.enabled = False

    # -- writes (never raise into the loop) ---------------------------------

    def write_equity(self, ts: datetime, equity: float) -> None:
        self._exec("INSERT INTO equity_ts (ts, equity) VALUES (%s, %s)", (ts, float(equity)))

    def write_decision(self, ts: datetime, symbol: str, venue: str, regime: str,
                       p_up: float, action: str, plugin: str) -> None:
        self._exec(
            "INSERT INTO decision_ts (ts, symbol, venue, regime, p_up, action, plugin)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (ts, symbol, venue, regime, float(p_up), action, plugin))

    def write_price(self, ts: datetime, base: str, venue: str, mid: float,
                    dislocation_bps: Optional[float]) -> None:
        self._exec(
            "INSERT INTO price_ts (ts, base, venue, mid, dislocation_bps) VALUES (%s,%s,%s,%s,%s)",
            (ts, base, venue, float(mid), dislocation_bps))

    def write_trade(self, ts: datetime, kind: str, symbol: str, strategy: str,
                    venue: str, pnl_usd: float) -> None:
        self._exec(
            "INSERT INTO trade_ts (ts, kind, symbol, strategy, venue, pnl_usd)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (ts, kind, symbol, strategy, venue, float(pnl_usd)))

    def _exec(self, sql: str, params: tuple) -> None:
        if not self.enabled or self._conn is None:
            return
        try:
            self._conn.cursor().execute(sql, params)
        except Exception:  # noqa: BLE001 — a storage hiccup must never break trading
            log.exception("timescale_write_failed")

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["TimescaleStore"]
