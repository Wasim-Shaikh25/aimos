"""Vendored code (§22). Surgical copies of borrowed modules, frozen by default.

Trading runtime may import: vt_factors, vt_validation, hb_mm, ft_protections,
jesse_engine. It must NOT import vt_research (import-linter contract, §22.3) —
that stack runs as a separate process (services/research).

NOTE: the reference implementations here are clean-room pure-math stubs written
from public formulas/specs so the package boundary, attribution scaffolding, and
smoke tests exist now. Replacing them with the actual upstream code at a pinned
SHA is an operator step (needs network to clone the upstreams) — record the SHA
and local diffs in vendor/VENDOR.md when done.
"""
