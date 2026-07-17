"""Go-live ladder tracker + testnet probe (§23.8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aimos.core.config import load_params
from aimos.core.schemas import OrderResult
from aimos.runtime.golive import GATES, GoLiveLadder, LiveNotAllowedError, guard_live_boot
from aimos.runtime.testnet_probe import run_testnet_probe


def test_ladder_locks_live_until_all_gates_signed(tmp_path):
    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    st = lad.status()
    assert st["live_allowed"] is False and st["percent"] == 0.0
    assert st["next"] == "Validated 12-month backtest"
    for gid, *_ in GATES:
        lad.mark(gid, note="ok")
    st2 = lad.status()
    assert st2["live_allowed"] is True and st2["percent"] == 100.0
    # persisted across instances
    assert GoLiveLadder(state_path=str(tmp_path / "gl.json")).live_allowed() is True


def test_ladder_paper_days_auto_progress(tmp_path):
    class _J:
        class conn:
            @staticmethod
            def execute(q, *a):
                class R:
                    def fetchone(self):
                        a0 = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
                        b0 = datetime.now(timezone.utc).isoformat()
                        return {"a": a0, "b": b0}
                return R()
    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"), journal=_J())
    paper = next(g for g in lad.status()["gates"] if g["id"] == "paper_4wk")
    assert 0.4 < paper["progress"] < 0.6  # ~14/28 days
    assert paper["status"] == "pending"   # progress alone never passes a gate


def test_testnet_probe_places_cancels_and_marks(tmp_path):
    class _Broker:
        def __init__(self):
            self.cancelled = False
        def place(self, plan, total_notional_after, open_positions_after):
            return OrderResult(ok=True, order_id="aimos-test", status="open", raw={})
        def cancel_all(self, symbol):
            self.cancelled = True
        def reconcile_on_start(self, syms):
            return {"ok": True}

    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    br = _Broker()
    res = run_testnet_probe(br, lad, symbol="BTC/USDT", notional_usdt=11.0)
    assert res["ok"] and br.cancelled
    # the testnet gate now shows auto progress (clock started)
    tgate = next(g for g in lad.status()["gates"] if g["id"] == "testnet_1wk")
    assert tgate["progress"] is not None


def test_boot_guard_allows_paper_refuses_incomplete_live(tmp_path):
    p = load_params()
    empty = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    # paper mode → always allowed
    p.mode = "paper"
    guard_live_boot(p, empty)  # no raise
    # live mode with an incomplete ladder → refuse to boot (fail-closed)
    p.mode = "live"
    with pytest.raises(LiveNotAllowedError):
        guard_live_boot(p, empty)
    # mandate enabled also triggers the guard even in paper mode
    p.mode = "paper"
    p.mandate.enabled = True
    with pytest.raises(LiveNotAllowedError):
        guard_live_boot(p, empty)


def test_boot_guard_allows_live_when_ladder_complete(tmp_path):
    lad = GoLiveLadder(state_path=str(tmp_path / "gl.json"))
    for gid, *_ in GATES:
        lad.mark(gid)
    p = load_params()
    p.mode = "live"
    guard_live_boot(p, lad)  # all gates signed → boots


def test_testnet_probe_reports_place_failure(tmp_path):
    class _Broker:
        def place(self, *a, **k):
            return OrderResult(ok=False, status="rejected", error="mandate not enabled", raw={})
    res = run_testnet_probe(_Broker(), GoLiveLadder(state_path=str(tmp_path / "gl.json")))
    assert res["ok"] is False and "mandate" in res["error"]
