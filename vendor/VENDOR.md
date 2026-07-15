# VENDOR.md — vendored code manifest (§22.1)

Records every vendored upstream: repo, pinned SHA, date, paths copied, local
modifications. Vendored code is **frozen by default** (§22.3 rule 1) — upgrades
are deliberate, human-approved events with before/after run cards.

> **Bootstrap status (2026-07-15):** package boundaries, attribution headers,
> import-linter isolation, LICENSES/, GPL_TRIPWIRE.md, and per-package smoke
> tests are in place. The modules currently hold **clean-room reference
> implementations** written from public formulas/specs, NOT upstream copies —
> the sandbox has no network to clone the upstreams. Vendoring the real code at
> a pinned SHA is the outstanding operator step; fill SHA/date/paths/diffs below
> when done.

| Package | Upstream | License | SHA | Date | Paths copied | Local diffs |
|---|---|---|---|---|---|---|
| `vendor/vt_factors` | HKUDS/Vibe-Trading | MIT | _pending_ | — | `agent/src/factors/` (zoos + operators + registry) | clean-room reference only |
| `vendor/vt_validation` | HKUDS/Vibe-Trading | MIT | _pending_ | — | backtest validation modules | clean-room reference only |
| `vendor/vt_research` | HKUDS/Vibe-Trading | MIT | _pending_ | — | ReAct/skills/swarm/journal-analyzer/shadow | separate runtime; runtime-import-forbidden |
| `vendor/hb_mm` | hummingbot/hummingbot | Apache-2.0 | _pending_ | — | Avellaneda–Stoikov math (pure-python paths) | clean-room reference only |
| `vendor/ft_protections` | freqtrade/freqtrade | GPL-3.0 ⚠️ | _pending_ | — | `freqtrade/plugins/protections/` | GPL tripwire; concept reimpl |
| `vendor/jesse_engine` | jesse-ai/jesse | MIT | _pending_ | — | core engine + metrics + indicators | clean-room reference only |

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
