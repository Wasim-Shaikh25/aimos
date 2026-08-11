"""Trade + decision journal with a tamper-evident hash chain (§8.1, §24.5,
card P4-T5).

Tables: decisions, outcomes, evidence_snapshots, agent_events, management.
Every row across all tables joins ONE hash chain (§24.5):
``row_hash = SHA256(prev_row_hash || canonical_json(row))`` — any retroactive
edit is detectable by the verifier (``aimos.journal.verify``). Columns are
derived 1:1 from the pydantic models with JSON columns for nested data (§25.8).

The backend is sqlite3 by default. When ``db_path`` is a SQLAlchemy URL
(``postgresql://...`` or ``sqlite:///...``) the journal is stored in that
database instead; for PostgreSQL each tenant lives in its own schema.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from aimos.core.schemas import DecisionRecord, ManagementEvent, OutcomeRecord

GENESIS = "0" * 64  # chain root


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _row_hash(prev_hash: str, payload_json: str) -> str:
    return hashlib.sha256((prev_hash + payload_json).encode("utf-8")).hexdigest()


_TABLES = ["decisions", "outcomes", "evidence_snapshots", "agent_events", "management"]


class Journal:
    def __new__(cls, db_path: Path | str = ":memory:", org_id: str = "local") -> "Journal":
        path_str = str(db_path)
        if cls is Journal and "://" in path_str:
            return object.__new__(_SqlJournal)
        return super().__new__(cls)

    def __init__(self, db_path: Path | str = ":memory:", org_id: str = "local") -> None:
        # check_same_thread=False: the FastAPI backend reads from a threadpool
        # (§15.1). Writes remain single-threaded through the orchestrator lock.
        self.org_id = org_id
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        c = self.conn
        for t in _TABLES:
            c.execute(
                f"""CREATE TABLE IF NOT EXISTS {t} (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT,
                    symbol TEXT,
                    "timestamp" TEXT,
                    payload TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    row_hash TEXT NOT NULL
                )"""
            )
        c.execute("CREATE TABLE IF NOT EXISTS chain_meta (id INTEGER PRIMARY KEY, tip TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS global_seq (gseq INTEGER)")
        if c.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone() is None:
            c.execute("INSERT INTO chain_meta(id, tip) VALUES (1, ?)", (GENESIS,))
        for t in _TABLES:
            c.execute(f'CREATE INDEX IF NOT EXISTS idx_{t}_sym ON {t}(symbol, "timestamp")')
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_did ON {t}(decision_id)")
        c.commit()

    # -- writes --------------------------------------------------------------

    def _tip(self) -> str:
        return self.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]

    def _append(self, table: str, decision_id, symbol, timestamp, payload: dict) -> str:
        pj = canonical_json(payload)
        prev = self._tip()
        rh = _row_hash(prev, pj)
        ts = str(timestamp)
        self.conn.execute(
            f'INSERT INTO {table}(decision_id, symbol, "timestamp", payload, prev_hash, row_hash)'
            " VALUES (?,?,?,?,?,?)",
            (decision_id, symbol, ts, pj, prev, rh),
        )
        self.conn.execute("UPDATE chain_meta SET tip=? WHERE id=1", (rh,))
        self.conn.commit()
        return rh

    def write_decision(self, record: DecisionRecord) -> str:
        payload = record.model_dump(mode="json")
        return self._append("decisions", record.decision_id, record.symbol, record.timestamp, payload)

    def write_outcome(self, record: OutcomeRecord) -> str:
        payload = record.model_dump(mode="json")
        return self._append("outcomes", record.decision_id, None, record.exit_time, payload)

    def write_management(self, event: ManagementEvent) -> str:
        payload = event.model_dump(mode="json")
        return self._append("management", event.decision_id, None, event.timestamp, payload)

    def write_evidence_snapshot(self, decision_id: str, symbol: str, timestamp, compressed: dict) -> str:
        return self._append("evidence_snapshots", decision_id, symbol, timestamp, compressed)

    def write_agent_event(self, name: str, timestamp, payload: dict) -> str:
        return self._append("agent_events", None, None, timestamp, {"agent": name, **payload})

    # -- reads / verification ------------------------------------------------

    def all_rows_in_order(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for t in _TABLES:
            for r in self.conn.execute(f"SELECT seq, payload, prev_hash, row_hash FROM {t}"):
                rows.append({"table": t, "seq_in_table": r["seq"], "payload": r["payload"],
                             "prev_hash": r["prev_hash"], "row_hash": r["row_hash"]})
        # global order = the order rows were appended = ascending row_hash chain;
        # reconstruct by following prev_hash links from GENESIS.
        return _chain_order(rows)

    def verify(self) -> tuple[bool, Optional[str]]:
        """Walk the chain; return (ok, first_broken_hash_or_None)."""
        prev = GENESIS
        for row in self.all_rows_in_order():
            expected = _row_hash(prev, row["payload"])
            if expected != row["row_hash"] or row["prev_hash"] != prev:
                return False, row["row_hash"]
            prev = row["row_hash"]
        return True, None

    def decision_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]

    def is_writable(self) -> bool:
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("ROLLBACK")
            return True
        except sqlite3.Error as exc:
            return False

    def close(self) -> None:
        self.conn.close()


class _SqlJournal(Journal):
    """SQLAlchemy-backed journal for PostgreSQL/SQLite URLs."""

    def __init__(self, db_path: Path | str, org_id: str = "local") -> None:
        self.org_id = org_id
        url = str(db_path)
        self._database_url = url
        from aimos.storage.db import get_storage_engine, normalize_sqlalchemy_url
        from sqlalchemy import (
            Column,
            Index,
            Integer,
            MetaData,
            String,
            Table,
            Text,
            text,
        )

        normalized = normalize_sqlalchemy_url(url)
        # Reuse the shared engine helper so journal + state + registry share the
        # same connection pool when they point at the same database URL.
        self._engine = get_storage_engine(normalized)
        self._dialect = self._engine.dialect.name
        self._schema = self._sanitize(org_id) if self._dialect == "postgresql" else None
        self._text = text

        metadata = MetaData()
        for t in _TABLES:
            Table(
                t,
                metadata,
                Column("seq", Integer, primary_key=True, autoincrement=True),
                Column("decision_id", String(255)),
                Column("symbol", String(64)),
                Column("timestamp", String(64), quote=True),
                Column("payload", Text, nullable=False),
                Column("prev_hash", String(64), nullable=False),
                Column("row_hash", String(64), nullable=False),
                Index(f"idx_{t}_sym", "symbol", "timestamp"),
                Index(f"idx_{t}_did", "decision_id"),
                schema=self._schema,
            )
        Table(
            "chain_meta",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("tip", String(64), nullable=False),
            schema=self._schema,
        )
        Table(
            "global_seq",
            metadata,
            Column("gseq", Integer),
            schema=self._schema,
        )

        with self._engine.begin() as conn:
            if self._dialect == "postgresql" and self._schema:
                conn.execute(self._text(f'CREATE SCHEMA IF NOT EXISTS "{self._schema}"'))
            metadata.create_all(conn)
            self._set_schema(conn)
            if self._dialect == "sqlite":
                conn.execute(
                    self._text("INSERT OR IGNORE INTO chain_meta(id, tip) VALUES (1, :tip)"),
                    {"tip": GENESIS},
                )
            else:
                conn.execute(
                    self._text(
                        "INSERT INTO chain_meta(id, tip) VALUES (1, :tip) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {"tip": GENESIS},
                )

        self.conn = _SQLConnection(self._engine, self._schema, self._dialect)

    def _sanitize(self, org_id: str) -> str:
        # PostgreSQL identifier limit is 63 bytes; keep it safe and collision-resistant
        # by restricting to alphanumerics, hyphen, underscore, then truncate.
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", org_id)
        return safe[:63]

    def _set_schema(self, conn) -> None:
        if self._dialect == "postgresql" and self._schema:
            conn.execute(self._text(f'SET LOCAL search_path TO "{self._schema}"'))

    def _tip(self) -> str:
        with self._engine.connect() as conn:
            self._set_schema(conn)
            row = conn.execute(self._text("SELECT tip FROM chain_meta WHERE id=1")).fetchone()
            return row[0] if row else GENESIS

    def _append(self, table: str, decision_id, symbol, timestamp, payload: dict) -> str:
        pj = canonical_json(payload)
        prev = self._tip()
        rh = _row_hash(prev, pj)
        ts = str(timestamp)
        with self._engine.begin() as conn:
            self._set_schema(conn)
            conn.execute(
                self._text(
                    f'INSERT INTO {table}(decision_id, symbol, "timestamp", payload, prev_hash, row_hash)'
                    " VALUES (:decision_id, :symbol, :timestamp, :payload, :prev_hash, :row_hash)"
                ),
                {
                    "decision_id": decision_id,
                    "symbol": symbol,
                    "timestamp": ts,
                    "payload": pj,
                    "prev_hash": prev,
                    "row_hash": rh,
                },
            )
            conn.execute(
                self._text("UPDATE chain_meta SET tip=:tip WHERE id=1"),
                {"tip": rh},
            )
        return rh

    def all_rows_in_order(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self._engine.connect() as conn:
            self._set_schema(conn)
            for t in _TABLES:
                result = conn.execute(
                    self._text(f"SELECT seq, payload, prev_hash, row_hash FROM {t}")
                )
                for r in result:
                    mapping = dict(r._mapping)
                    rows.append({
                        "table": t,
                        "seq_in_table": mapping["seq"],
                        "payload": mapping["payload"],
                        "prev_hash": mapping["prev_hash"],
                        "row_hash": mapping["row_hash"],
                    })
        return _chain_order(rows)

    def decision_count(self) -> int:
        with self._engine.connect() as conn:
            self._set_schema(conn)
            row = conn.execute(self._text("SELECT COUNT(*) c FROM decisions")).fetchone()
            return int(row[0]) if row else 0

    def is_writable(self) -> bool:
        try:
            with self._engine.begin() as conn:
                self._set_schema(conn)
                conn.execute(self._text("UPDATE chain_meta SET tip=tip WHERE id=1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        self._engine.dispose()


class _SQLConnection:
    """Lightweight adapter exposing ``conn.execute(...).fetchone/all()``."""

    def __init__(self, engine, schema: str | None, dialect: str) -> None:
        self._engine = engine
        self._schema = schema
        self._dialect = dialect

    def _set_schema(self, conn) -> None:
        if self._dialect == "postgresql" and self._schema:
            from sqlalchemy import text

            conn.execute(text(f'SET LOCAL search_path TO "{self._schema}"'))

    @staticmethod
    def _convert(sql: str, params: Any) -> tuple[str, dict[str, Any]]:
        if params is None:
            return sql, {}
        if isinstance(params, (tuple, list)):
            mapping: dict[str, Any] = {}
            for i, value in enumerate(params):
                sql = sql.replace("?", f":p{i}", 1)
                mapping[f"p{i}"] = value
            return sql, mapping
        return sql, dict(params)

    def execute(self, sql: str, parameters: Any = None):
        from sqlalchemy import text

        sql, mapping = self._convert(sql, parameters)
        with self._engine.begin() as conn:
            self._set_schema(conn)
            result = conn.execute(text(sql), mapping)
            rows = [dict(r._mapping) for r in result]
        return _SQLCursor(rows)

    def commit(self) -> None:
        # engine.begin() commits automatically; writes through this adapter are committed
        # immediately so callers that expect sqlite3's conn.execute(); conn.commit() still work.
        return None

    def close(self) -> None:
        return None


class _SQLCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._iter = iter(rows)

    def fetchone(self) -> dict[str, Any] | None:
        try:
            return next(self._iter)
        except StopIteration:
            return None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


def _chain_order(rows: list[dict]) -> list[dict]:
    """Order rows by following prev_hash links from GENESIS."""
    by_prev = {r["prev_hash"]: r for r in rows}
    ordered: list[dict] = []
    prev = GENESIS
    while prev in by_prev:
        r = by_prev[prev]
        ordered.append(r)
        prev = r["row_hash"]
    return ordered


__all__ = ["GENESIS", "Journal", "canonical_json"]
