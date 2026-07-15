# VENDOR.md — vendored code manifest (§22.1)

Records every vendored upstream: repo, pinned SHA, date, paths copied, local
modifications. Vendored code is **frozen by default** (§22.3 rule 1) — upgrades
are deliberate, human-approved events with before/after run cards.

| Package | Upstream | License | SHA | Date | Paths copied | Local diffs |
|---|---|---|---|---|---|---|
| _(none yet — Phase 1.5 vendor bootstrap, card P15-T4)_ | | | | | | |

## Pinned dependency versions
Exact versions are pinned in `pyproject.toml` (trading runtime) and
`services/research/pyproject.toml` (research stack). No floating ranges (§25.8).
