"""Journal hash chain + labeling tests (§8.1, §8.2, §24.5 — card P4-T5)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from aimos.journal.journal import Journal, canonical_json
from aimos.learning.labeling import BarrierConfig, triple_barrier_label
from tests.conftest import make_mu

ROOT = Path(__file__).resolve().parents[1]
TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _decision():
    from aimos.core.schemas import Action, DecisionRecord, TradePlan
    plan = TradePlan(plugin="RiskOff", symbol="SOL", action=Action.NO_TRADE)
    return DecisionRecord(timestamp=TS, symbol="SOL", understanding=make_mu(),
                          candidates=[], chosen=plan, mode="backtest", decision_id="SOL-1")


def test_journal_round_trip_and_chain():
    j = Journal(":memory:")
    j.write_decision(_decision())
    j.write_decision(_decision())
    assert j.decision_count() == 2
    ok, broken = j.verify()
    assert ok and broken is None


def test_verifier_detects_tampering(tmp_path):
    db = tmp_path / "j.sqlite"
    j = Journal(str(db))
    j.write_decision(_decision())
    j.write_decision(_decision())
    # tamper: edit a payload directly, leaving the stored hash stale
    j.conn.execute("UPDATE decisions SET payload = payload || ' ' WHERE seq = 1")
    j.conn.commit()
    ok, broken = j.verify()
    assert not ok


def test_verifier_cli(tmp_path):
    db = tmp_path / "j.sqlite"
    j = Journal(str(db))
    j.write_decision(_decision())
    j.close()
    r = subprocess.run([sys.executable, "-m", "aimos.journal.verify", str(db)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "OK" in r.stdout


# ---- triple-barrier labeler (§8.2) ----

def test_label_upper_barrier_first():
    cfg = BarrierConfig(upper_atr=1.5, lower_atr=1.5, noise_atr=0.3)
    # price 100, atr 2 → upper 103, lower 97. Path hits 103 first.
    assert triple_barrier_label(100.0, 2.0, [101, 102, 103.5, 96], cfg, long=True) == 1


def test_label_lower_barrier_first():
    cfg = BarrierConfig()
    assert triple_barrier_label(100.0, 2.0, [99, 98, 96.5, 105], cfg, long=True) == 0


def test_label_timeout_noise_dropped():
    cfg = BarrierConfig(upper_atr=1.5, lower_atr=1.5, noise_atr=0.3)
    # never hits ±3; ends at 100.2 → |move| 0.2 < 0.3*2=0.6 → drop (None)
    assert triple_barrier_label(100.0, 2.0, [100.1, 100.2, 100.15, 100.2], cfg, long=True) is None


def test_label_short_mirrors():
    cfg = BarrierConfig()
    # short: hitting the lower price (favorable) → label 1
    assert triple_barrier_label(100.0, 2.0, [99, 98, 96.5], cfg, long=False) == 1
