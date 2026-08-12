"""T-011 — go-live ``backtest_validated`` gate requires a valid run card."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from aimos.runtime.golive import GoLiveLadder


def _write_card(tmp_path: Path, name: str, p: float) -> None:
    d = tmp_path / "runcards"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(
        yaml.safe_dump({"validation": {"permutation_p": p}, "verdict": "edge"}),
        encoding="utf-8",
    )


def test_rejects_with_no_run_card(tmp_path):
    """T-011.1: tick gate with no run card is rejected."""
    state = tmp_path / "go_live.json"
    state.write_text(json.dumps({"gates": {}, "markers": {}}), encoding="utf-8")
    ladder = GoLiveLadder(state_path=str(state), runcards_dir=str(tmp_path / "runcards"))
    res = ladder.mark("backtest_validated", note="operator")
    assert res["ok"] is False
    assert "permutation" in res["error"].lower()


def test_rejects_with_high_p_run_card(tmp_path):
    """T-011.2: tick with p ≥ 0.05 run card is rejected."""
    _write_card(tmp_path, "bad", 0.07)
    state = tmp_path / "go_live.json"
    state.write_text(json.dumps({"gates": {}, "markers": {}}), encoding="utf-8")
    ladder = GoLiveLadder(state_path=str(state), runcards_dir=str(tmp_path / "runcards"))
    res = ladder.mark("backtest_validated")
    assert res["ok"] is False
    assert "p < 0.05" in res["error"]


def test_accepts_with_valid_run_card(tmp_path):
    """T-011.3: tick with a valid run card is accepted."""
    _write_card(tmp_path, "good", 0.01)
    state = tmp_path / "go_live.json"
    state.write_text(json.dumps({"gates": {}, "markers": {}}), encoding="utf-8")
    ladder = GoLiveLadder(state_path=str(state), runcards_dir=str(tmp_path / "runcards"))
    res = ladder.mark("backtest_validated")
    assert res["ok"] is True
    assert ladder._passed("backtest_validated") is True


def test_still_rejects_out_of_order(tmp_path):
    """T-011.4: gate order still enforced even with a valid run card."""
    _write_card(tmp_path, "good", 0.01)
    state = tmp_path / "go_live.json"
    state.write_text(json.dumps({"gates": {}, "markers": {}}), encoding="utf-8")
    ladder = GoLiveLadder(state_path=str(state), runcards_dir=str(tmp_path / "runcards"))
    res = ladder.mark("paper_4wk")
    assert res["ok"] is False
    assert "backtest_validated" in res["error"]
