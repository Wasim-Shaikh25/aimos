"""Go-live ladder tracker (§23.8). Turns the go-live process into a checklist with
progress, persisted to a state file, surfaced on the UI.

Live real-money trading is fail-closed: ``live_allowed`` is True only when EVERY
gate is passed. Time-based gates (paper, testnet, canary) show auto-computed
progress but still require an explicit operator sign-off to mark them passed — so
nothing advances to real money on a timer. Not in the linted layers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aimos.runtime.atomic_io import atomic_write_json

# (id, title, kind, detail, auto_days) — auto_days drives the progress bar for
# time-based gates; None = a pure operator sign-off.
GATES = [
    ("backtest_validated", "Validated 12-month backtest", "manual",
     "Permutation p<0.05, bootstrap CI, benchmarks beaten (§9.3/§20.2)", None),
    ("paper_4wk", "4 weeks paper trading", "auto",
     "28+ days of journaled paper decisions", 28),
    ("testnet_1wk", "1 week on exchange testnet", "auto",
     "Real orders placed on testnet + reconciled (scripts/testnet_order.py)", 7),
    ("security_signoff", "Security signoff + restore drill", "manual",
     "Keys withdrawal-disabled, backup/restore drill, incident runbook (§23.4/§23.5)", None),
    ("canary_10pct", "10% canary", "auto",
     "Live at 10% size, paper-vs-live divergence within tolerance, 14+ days", 14),
    ("scaling", "Scale in 25% steps", "manual",
     "Divergence-gated scaling to full size (§23.8)", None),
]
_SECONDS_PER_DAY = 86400.0


class GoLiveLadder:
    def __init__(self, state_path: str = "state/go_live.json", journal=None) -> None:
        self.path = Path(state_path)
        self.journal = journal
        self._state = self._load()

    def _load(self) -> dict:
        for candidate in (self.path, self.path.with_suffix(self.path.suffix + ".bak")):
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except ValueError:
                    # torn primary — fall through to the last-good .bak so a bad
                    # shutdown cannot silently wipe operator sign-offs (finding M8)
                    continue
        return {"gates": {}, "markers": {}}

    def _save(self) -> None:
        # Keep the previous good file as .bak, then write atomically. The go-live
        # sign-off record is high-value (it gates real money) — a torn write must
        # never destroy it (audit finding M8).
        if self.path.exists():
            try:
                self.path.replace(self.path.with_suffix(self.path.suffix + ".bak"))
            except OSError:
                pass
        atomic_write_json(self.path, self._state)

    # -- markers set by automation (e.g. the testnet script) ----------------

    def set_marker(self, key: str, value=None) -> None:
        self._state.setdefault("markers", {})[key] = value or _now_iso()
        self._save()

    def mark(self, gate_id: str, note: str = "") -> dict:
        if gate_id not in {g[0] for g in GATES}:
            return {"ok": False, "error": f"unknown gate {gate_id!r}"}
        self._state.setdefault("gates", {})[gate_id] = {"status": "passed", "note": note,
                                                        "marked_at": _now_iso()}
        self._save()
        return {"ok": True, "gate": gate_id}

    def unmark(self, gate_id: str) -> dict:
        self._state.get("gates", {}).pop(gate_id, None)
        self._save()
        return {"ok": True, "gate": gate_id}

    # -- auto progress -------------------------------------------------------

    def _paper_days(self) -> float:
        if self.journal is None:
            return 0.0
        row = self.journal.conn.execute(
            "SELECT MIN(timestamp) a, MAX(timestamp) b FROM decisions").fetchone()
        if not row or not row["a"]:
            return 0.0
        try:
            a = datetime.fromisoformat(row["a"]); b = datetime.fromisoformat(row["b"])
        except ValueError:
            return 0.0
        return max((b - a).total_seconds() / _SECONDS_PER_DAY, 0.0)

    def _auto_days(self, gate_id: str, marker_key: str) -> float:
        if gate_id == "paper_4wk":
            return self._paper_days()
        started = self._state.get("markers", {}).get(marker_key)
        if not started:
            return 0.0
        try:
            t0 = datetime.fromisoformat(started)
        except ValueError:
            return 0.0
        return max((_now() - t0).total_seconds() / _SECONDS_PER_DAY, 0.0)

    def status(self) -> dict:
        gates_out = []
        passed = 0
        for gid, title, kind, detail, auto_days in GATES:
            g = self._state.get("gates", {}).get(gid, {})
            is_passed = g.get("status") == "passed"
            progress = None
            hint = ""
            if auto_days:
                days = self._auto_days(gid, {"testnet_1wk": "testnet_started",
                                             "canary_10pct": "canary_started"}.get(gid, ""))
                progress = min(days / auto_days, 1.0)
                hint = f"{days:.1f} / {auto_days} days"
            if is_passed:
                passed += 1
            gates_out.append({
                "id": gid, "title": title, "kind": kind, "detail": detail,
                "status": "passed" if is_passed else "pending",
                "progress": progress, "hint": hint,
                "note": g.get("note", ""), "marked_at": g.get("marked_at"),
            })
        total = len(GATES)
        nxt = next((g["title"] for g in gates_out if g["status"] != "passed"), None)
        return {
            "gates": gates_out, "passed": passed, "total": total,
            "percent": round(100.0 * passed / total, 1),
            "live_allowed": passed == total,
            "next": nxt,
        }

    def live_allowed(self) -> bool:
        return self.status()["live_allowed"]


class LiveNotAllowedError(RuntimeError):
    """Raised when the app is asked to run live before the go-live ladder is complete."""


def guard_live_boot(params, ladder: Optional["GoLiveLadder"] = None) -> None:
    """Hard fail-closed check: refuse to BOOT in live mode (or with the mandate
    enabled) until every §23.8 go-live gate is signed off. Paper mode is never
    affected. This is belt-and-suspenders on top of the mandate + Controls locks —
    a misconfigured deploy physically cannot trade real money early."""
    pd = params.model_dump()
    mode = str(pd.get("mode", "paper")).lower()
    mandate_on = bool((pd.get("mandate") or {}).get("enabled", False))
    if mode != "live" and not mandate_on:
        return  # paper — nothing to guard
    lad = ladder or GoLiveLadder()
    if not lad.live_allowed():
        st = lad.status()
        raise LiveNotAllowedError(
            f"refusing to start live (mode={mode}, mandate={mandate_on}): only "
            f"{st['passed']}/{st['total']} go-live gates signed off — next: {st['next']}. "
            f"Complete the ladder on the Go-Live screen / specs/OPERATIONS.md (§23.8).")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


__all__ = ["GATES", "GoLiveLadder", "LiveNotAllowedError", "guard_live_boot"]
