#!/usr/bin/env python3
"""Zero-hardcoding lint for the decision-path layers (§23.12, card P0-T4).

Scans ``aimos/observation/``, ``aimos/intelligence/`` and ``aimos/execution/``
for bare numeric literals outside a small allowlist. Every tunable must come
from ``config/*.yaml`` via the ``Params`` tree, so a literal like ``rel_vol >
2.0`` in decision-path code is a violation with the fix "move to config".

Allowlist (per §23.12): 0, 1, -1, 2 — for arithmetic, indices and math
constants. ``__init__.py`` and any ``# noqa: magic`` line are exempt.

Usage: python scripts/check_magic_numbers.py
Exit 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = ["observation", "intelligence", "execution"]
ALLOWED = {0, 1, 2}  # -1 handled via UnaryOp below
NOQA = "# noqa: magic"


class _Visitor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.violations: list[tuple[int, str]] = []
        self._unary_neg_nodes: set[int] = set()

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        # Allow the literal -1 (USub over constant 1).
        if (
            isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and node.operand.value == 1
        ):
            self._unary_neg_nodes.add(id(node.operand))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bool):  # bools are fine
            return
        if not isinstance(node.value, (int, float)):
            return
        if id(node) in self._unary_neg_nodes:
            return
        if node.value in ALLOWED:
            return
        lineno = node.lineno
        line = self.source_lines[lineno - 1] if lineno <= len(self.source_lines) else ""
        if NOQA in line:
            return
        self.violations.append((lineno, repr(node.value)))


def _check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    visitor = _Visitor(text.splitlines())
    visitor.visit(tree)
    rel = path.relative_to(ROOT)
    return [f"{rel}:{ln}: magic number {val} — move to config (§23.12)" for ln, val in visitor.violations]


def main() -> int:
    violations: list[str] = []
    for layer in LAYERS:
        base = ROOT / "aimos" / layer
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            violations.extend(_check_file(path))
    if violations:
        print("Magic-number lint FAILED:")
        for v in violations:
            print("  " + v)
        return 1
    print("Magic-number lint OK (decision-path layers clean).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
