"""Feature monitor agent — aggregation + forced coverage (no runtime needed)."""

from __future__ import annotations

from aimos.runtime.monitor_agent import FeatureMonitorAgent, degraded, failing, ok


def test_run_once_aggregates_coverage():
    probes = {
        "a": lambda: ok("a", "fine"),
        "b": lambda: degraded("b", "warming"),
        "c": lambda: failing("c", "broken"),
        "d": lambda: ok("d"),
    }
    rep = FeatureMonitorAgent(probes).run_once()
    assert rep["summary"] == {"ok": 2, "degraded": 1, "failing": 1, "total": 4}
    assert rep["coverage_pct"] == 50.0  # 2/4 ok
    assert rep["forced"] is False
    assert {f["name"] for f in rep["features"]} == {"a", "b", "c", "d"}


def test_probe_exception_becomes_failing():
    def boom():
        raise RuntimeError("nope")

    rep = FeatureMonitorAgent({"x": boom}).run_once()
    x = rep["features"][0]
    assert x["status"] == "failing"
    assert "probe error" in x["detail"]


class _Ctl:
    def __init__(self):
        self.calls = []

    def set(self, name, value):
        self.calls.append((name, value))
        return {"ok": True}


def test_force_coverage_enables_safe_flags_once():
    ctl = _Ctl()
    agent = FeatureMonitorAgent({"a": lambda: ok("a")}, feature_ctl=ctl, force_coverage=True)
    agent.force_coverage()
    agent.force_coverage()  # idempotent — only flips once
    assert ctl.calls == [("cross_exchange", True), ("scalp", True)]
    assert agent.run_once()["forced"] is True


def test_force_coverage_noop_when_disabled():
    ctl = _Ctl()
    agent = FeatureMonitorAgent({"a": lambda: ok("a")}, feature_ctl=ctl, force_coverage=False)
    agent.force_coverage()
    assert ctl.calls == []
    assert agent.run_once()["forced"] is False
