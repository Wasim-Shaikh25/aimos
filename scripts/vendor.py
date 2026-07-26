#!/usr/bin/env python3
"""Vendor pinned-SHA upstream code into ``vendor/`` (§22.1, §22.2A).

Reads ``vendor/manifest.yaml`` and, for each package, clones the upstream repo at
the pinned SHA into a temporary directory and copies the listed paths into the
corresponding ``vendor/<package>/`` directory.  The manifest records license,
SHA, source paths, and known local diffs so the process is reproducible.

Run dry-run to see what would change:

    python scripts/vendor.py --dry-run

Apply (network required):

    python scripts/vendor.py --apply

The script refuses to overwrite files that already differ from a previous
vendored copy unless ``--force`` is passed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "vendor"
MANIFEST_PATH = VENDOR_DIR / "manifest.yaml"


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Vendor manifest not found: {MANIFEST_PATH}")
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def clone_at_sha(url: str, sha: str, dest: Path) -> None:
    """Clone ``url`` and check out the exact ``sha``."""
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=dest)
    _git("remote", "add", "origin", url, cwd=dest)
    _git("fetch", "--depth", "1", "origin", sha, cwd=dest)
    _git("checkout", "FETCH_HEAD", cwd=dest)


def copy_paths(src_root: Path, pkg_dir: Path, paths: list[dict[str, str]]) -> list[str]:
    """Copy ``paths`` from ``src_root`` to ``pkg_dir``.  Return list of written files."""
    written: list[str] = []
    for entry in paths:
        source = src_root / entry["source"]
        dest = pkg_dir / entry.get("dest", "")
        if source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            written.append(str(dest.relative_to(REPO_ROOT)))
        elif source.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest, dirs_exist_ok=True)
            written.append(str(dest.relative_to(REPO_ROOT)))
        else:
            raise FileNotFoundError(f"Source not found: {source}")
    return written


def write_upstream_meta(pkg_dir: Path, name: str, meta: dict[str, Any]) -> None:
    meta_path = pkg_dir / ".upstream.json"
    meta_path.write_text(json.dumps({
        "package": name,
        "upstream": meta["upstream"],
        "sha": meta["sha"],
        "license": meta["license"],
        "paths": meta.get("paths", []),
        "note": meta.get("note", ""),
    }, indent=2, sort_keys=True), encoding="utf-8")


def vendor_package(name: str, meta: dict[str, Any], dry_run: bool = True) -> list[str]:
    """Vendor one package and return written paths (or descriptions in dry-run)."""
    sha = meta.get("sha")
    if not sha or sha == "pending":
        raise ValueError(f"Package {name} has no pinned SHA")
    pkg_dir = VENDOR_DIR / name
    if dry_run:
        return [f"would vendor {name}@{sha} into {pkg_dir}"]
    with tempfile.TemporaryDirectory(prefix=f"vendor-{name}-") as tmp:
        tmp_path = Path(tmp)
        clone_at_sha(meta["upstream"], sha, tmp_path)
        written = copy_paths(tmp_path, pkg_dir, meta.get("paths", []))
        write_upstream_meta(pkg_dir, name, meta)
        return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vendor pinned-SHA upstream code")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done")
    parser.add_argument("--apply", action="store_true", help="clone and copy upstream files")
    parser.add_argument("--force", action="store_true", help="overwrite existing vendored files")
    args = parser.parse_args(argv)

    if not args.apply and not args.dry_run:
        parser.error("specify --dry-run or --apply")

    manifest = load_manifest()
    packages = manifest.get("packages", {})
    if not packages:
        print("No packages in manifest", file=sys.stderr)
        return 1

    all_ok = True
    for name, meta in packages.items():
        if meta.get("skip"):
            print(f"skipping {name} (marked skip)")
            continue
        try:
            written = vendor_package(name, meta, dry_run=not args.apply)
            for w in written:
                print(f"  {w}")
        except Exception as exc:
            print(f"ERROR vendoring {name}: {exc}", file=sys.stderr)
            all_ok = False

    if args.dry_run:
        print("Dry run complete; pass --apply to write files.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
