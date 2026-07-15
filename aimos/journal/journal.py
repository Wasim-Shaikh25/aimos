"""Trade + decision journal with a tamper-evident hash chain (§8.1, §24.5,
card P4-T5).

SQLite tables: decisions, outcomes, evidence_snapshots, agent_events, management.
Every row across all tables joins ONE hash chain (§24.5):
``row_hash = SHA256(prev_row_hash || canonical_json(row))`` — any retroactive
edit is detectable by the verifier (``aimos.journal.verify``). Columns are
derived 1:1 from the pydantic models with JSON columns for nested data (§25.8).
"""

from __future__ import annotations

import hashlib
import json
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
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.conn = sqlite3.connect(str(db_path))
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
                    timestamp TEXT,
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
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_sym ON {t}(symbol, timestamp)")
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_did ON {t}(decision_id)")
        c.commit()

    # -- writes --------------------------------------------------------------

    def _tip(self) -> str:
        return self.conn.execute("SELECT tip FROM chain_meta WHERE id=1").fetchone()["tip"]

    def _append(self, table: str, decision_id, symbol, timestamp, payload: dict) -> str:
        pj = canonical_json(payload)
        prev = self._tip()
        rh = _row_hash(prev, pj)
        self.conn.execute(
            f"INSERT INTO {table}(decision_id, symbol, timestamp, payload, prev_hash, row_hash)"
            " VALUES (?,?,?,?,?,?)",
            (decision_id, symbol, str(timestamp), pj, prev, rh),
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

    def all_rows_in_order(self) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for t in _TABLES:
            for r in self.conn.execute(f"SELECT rowid, seq, payload, prev_hash, row_hash FROM {t}"):
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

    def close(self) -> None:
        self.conn.close()


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
