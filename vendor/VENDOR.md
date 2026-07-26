# VENDOR.md — vendored code manifest (§22.1)

Records every vendored upstream: repo, pinned SHA, date, paths copied, local
modifications. Vendored code is **frozen by default** (§22.3 rule 1) — upgrades
are deliberate, human-approved events with before/after run cards.

> **Vendoring status (2026-07-26):** package boundaries, attribution headers,
> import-linter isolation, LICENSES/, GPL_TRIPWIRE.md, and per-package smoke
> tests are in place.  The modules currently hold **clean-room reference
> implementations** written from public formulas/specs.  A reproducible vendoring
> script (`scripts/vendor.py`) reads `vendor/manifest.yaml`, clones each upstream
> at the pinned SHA, and copies the listed paths into `vendor/<package>/`.
> Run `python scripts/vendor.py --dry-run` to preview; run with `--apply` (network
> required) to materialize upstream copies.  Some packages remain `skip: true` in
> the manifest until their exact upstream paths and any import rewrites are
> verified by the operator.

| Package | Upstream | License | SHA | Date | Paths copied | Local diffs |
|---|---|---|---|---|---|---|
| `vendor/vt_factors` | HKUDS/Vibe-Trading | MIT | `4cede84` | — | `agent/src/factors/` (zoos + operators + registry) | clean-room reference; import rewrite needed |
| `vendor/vt_validation` | HKUDS/Vibe-Trading | MIT | `4cede84` | — | `agent/backtest/validation.py` | clean-room wrapper; signatures differ |
| `vendor/vt_research` | HKUDS/Vibe-Trading | MIT | `4cede84` | — | ReAct/skills/swarm/journal-analyzer/shadow | separate runtime; runtime-import-forbidden |
| `vendor/hb_mm` | hummingbot/hummingbot | Apache-2.0 | `816b8ab` | — | Avellaneda–Stoikov math (pure-python paths) | clean-room reference; exact paths TBD |
| `vendor/ft_protections` | freqtrade/freqtrade | GPL-3.0 ⚠️ | `e5fd2fe` | — | `freqtrade/plugins/protections/` | GPL tripwire; concept reimplementation |
| `vendor/jesse_engine` | jesse-ai/jesse | MIT | `fa63531` | — | core engine + metrics + indicators | clean-room reference; exact paths TBD |

## Reproducible vendoring

Run the vendoring script (network required) after reviewing/updating `vendor/manifest.yaml`:

```bash
python scripts/vendor.py --dry-run
python scripts/vendor.py --apply
```

The script refuses to act without `--dry-run` or `--apply`, records each package's
upstream SHA in `vendor/<package>/.upstream.json`, and preserves the clean-room
stubs until `--apply` is run.

`cryptofeed`, `optuna`, `ccxt`, `lightgbm` etc. remain normal pinned pip deps
(§22.2E) — vendoring unmodified libraries adds cost, zero benefit.

## Pinned dependency versions
Exact versions are pinned in `pyproject.toml` (trading runtime) and
`services/research/pyproject.toml` (research stack). No floating ranges (§25.8).

## Namespace discipline (§22.3 rule 3)
Trading runtime may import `vendor.vt_factors`, `vendor.hb_mm`,
`vendor.ft_protections`, `vendor.jesse_engine` — and NOTHING from
`vendor.vt_research` (import-linter contract). The research stack is reachable
only via the `services/research` process boundary.
