"""Model registry: append, promote, demote, drift."""

from __future__ import annotations

from aimos.learning.registry import ModelEntry, ModelRegistry


def test_registry_append_and_latest(tmp_path):
    reg = ModelRegistry(tmp_path / "registry.json")
    reg.add(ModelEntry(path="/tmp/a.json", val_auc=0.6, brier=0.2,
                       n_features=70, n_samples=1000, status="candidate"))
    latest = reg.latest()
    assert latest is not None
    assert latest.path == "/tmp/a.json"
    assert latest.status == "candidate"


def test_registry_promote_and_drift(tmp_path):
    reg = ModelRegistry(tmp_path / "registry.json")
    reg.add(ModelEntry(path="/tmp/first.json", val_auc=0.6, brier=0.2,
                       n_features=70, n_samples=1000))
    reg.promote("/tmp/first.json")
    assert reg.latest().status == "promoted"

    reg.add(ModelEntry(path="/tmp/second.json", val_auc=0.6, brier=0.5,
                       n_features=70, n_samples=1000))
    drift = reg.check_drift(0.5, 0.2, "/tmp/second.json", threshold=0.20)
    assert drift["degraded"] is True
    assert reg.latest("demoted") is not None
