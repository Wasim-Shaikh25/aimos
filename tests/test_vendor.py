"""Vendor vendoring manifest, script, and runtime-import rules (§22)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "vendor"
MANIFEST = VENDOR_DIR / "manifest.yaml"
VENDOR_SCRIPT = REPO_ROOT / "scripts" / "vendor.py"


def test_manifest_exists_and_is_valid_yaml():
    assert MANIFEST.exists()
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert "packages" in manifest
    for name, meta in manifest["packages"].items():
        assert "upstream" in meta
        assert "license" in meta
        assert "sha" in meta
        if not meta.get("skip"):
            assert meta["sha"] and meta["sha"] != "pending", f"{name} has no pinned SHA"
            assert meta.get("paths"), f"{name} has no paths"


def test_vendor_script_dry_run_runs():
    result = subprocess.run(
        [sys.executable, str(VENDOR_SCRIPT), "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Dry run complete" in result.stdout or result.stdout.count("would vendor") > 0


def test_vendor_modules_are_importable():
    from vendor.vt_factors import alpha_momentum, cross_sectional_zscore
    from vendor.vt_validation import bootstrap_sharpe_ci, permutation_pvalue
    from vendor.hb_mm import quote_prices
    from vendor.jesse_engine import max_drawdown, total_return

    assert callable(alpha_momentum)
    assert callable(cross_sectional_zscore)
    assert callable(bootstrap_sharpe_ci)
    assert callable(permutation_pvalue)
    assert callable(quote_prices)
    assert callable(max_drawdown)
    assert callable(total_return)


def test_gpl_tripwire_is_present():
    tripwire = VENDOR_DIR / "GPL_TRIPWIRE.md"
    assert tripwire.exists()
    text = tripwire.read_text(encoding="utf-8")
    assert "freqtrade" in text.lower() or "gpl" in text.lower()


def test_runtime_does_not_import_vt_research():
    # import-linter enforces this, but the rule is critical enough to test directly.
    import aimos

    source = Path(aimos.__file__).resolve().parent
    hits = list(source.rglob("*.py"))
    for path in hits:
        content = path.read_text(encoding="utf-8", errors="ignore")
        assert "vendor.vt_research" not in content, f"{path} imports forbidden vendor.vt_research"
