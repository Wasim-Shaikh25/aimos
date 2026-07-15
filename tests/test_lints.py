"""Phase-0 gate + lint tests (cards P0-T1/T4/T5).

* ``import aimos`` is clean (phase gate).
* import-linter contracts exist with the 3 layer rules.
* no-naive-datetime lint passes over ``aimos/``.
* magic-number lint passes over the decision-path layers.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_import_aimos_clean():
    import aimos  # noqa: F401

    assert aimos.__version__


def test_import_linter_contracts_present():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    contracts = data["tool"]["importlinter"]["contracts"]
    assert len(contracts) >= 3
    # the layers contract lists the three layers in import order
    layers = [c for c in contracts if c["type"] == "layers"]
    assert layers, "a layers-type contract must exist"
    joined = " ".join(layers[0]["layers"])
    assert "observation" in joined
    assert "intelligence" in joined
    assert "execution" in joined


def test_no_naive_datetime_lint():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_naive_datetime.py")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_magic_number_lint():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_magic_numbers.py")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_import_linter_passes():
    # lint-imports must be able to build the graph and satisfy the contracts.
    r = subprocess.run(
        ["lint-imports"], capture_output=True, text=True, cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr
