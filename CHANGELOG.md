# Changelog

Everything implemented, newest first. **Update this file after every change** —
one entry per meaningful unit of work (see `CLAUDE.md`). Format loosely follows
Keep a Changelog. Dates are the working session, not calendar-exact.

## Unreleased

### Added
- **TimescaleDB time-series store** (`aimos/storage/timescale.py`, optional): writes
  equity / decisions / prices / trades to hypertables when `AIMOS_TIMESCALE_DSN`
  is set and `psycopg` is installed (`pip install '.[timescale]'`); safe no-op
  otherwise. Wired into the serve loop; `docker-compose` points it at the
  TimescaleDB service. The SQLite hash-chained journal stays the system of record.
- **Persistent journal by default**: `paper.journal_path` now defaults to
  `state/aimos.sqlite` (was in-memory).
- **Docs reorganized**: consolidated Markdown into `specs/` (ARCHITECTURE, MODELS,
  OPERATIONS, STATUS); new root `README.md`, this `CHANGELOG.md`, `CLAUDE.md`, and
  Cursor rules that require reading `specs/STATUS.md` + this changelog first.

### History (chronological)
- **Hard boot guard** — the app refuses to start in `mode: live` (or with the
  mandate enabled) until every go-live gate is signed off (`guard_live_boot`).
- **Go-live ladder tracker** — the six §23.8 gates as a checklist with UI progress
  (`/golive`), CONFIRM-gated operator sign-off, a testnet order probe
  (`scripts/testnet_order.py`), and `GO_LIVE.md` runbook.
- **Runtime feature toggles** (UI Controls screen + Telegram `/features`, `/enable`,
  `/disable`) for the safe keyless flags (scalp, cross_exchange); live/funded flags
  are LOCKED and refuse to flip.
- **Phase D** — gated live multi-venue executor (`LiveBroker` + `MultiVenueLiveRouter`,
  mandate + withdrawal gated, mock-tested), read-only key **preflight self-check**
  + Connections panel, secret loading (file + env), real balance UI; **scalp enabled**
  (MomentumScalp + proxy micro-engine).
- **Phase C** — decision **mind-map** (`/mindmap`): evidence → fusion → regime →
  strategies → chosen as a node graph.
- **Phase B** — **simulated multi-venue arb execution** (two-leg buy-cheap/sell-rich,
  inventory-constrained), **Trade History**, **Balances**, real **Performance**.
- **Phase A** — full **per-venue analysis** across binance/kraken/coinbase +
  **multi-platform price matrix** + per-venue Engines.
- **One deployable server** — `aimos.runtime.serve` = dashboard + paper loop +
  Telegram, auto-started; persistent journal option.
- **Universe wired into the runtime** — top-N by volume (discovery + seed fallback),
  refresh, cross-venue-biased selection; live-polling UI; Engines/Strategies/Models
  screens.
- **Cross-exchange arbitrage (P8)** plugin + multi-venue data; fixed `.gitignore`
  that had been excluding the whole `aimos/data/` package.
- **Runnable paper mode** — feature flags, `.env` templates, end-to-end paper loop,
  working React dashboard, `./run.sh` one-command full stack; stubs replaced with
  real implementations.
- **Phases 0–6** (original build contract): contracts → data infra → universe
  manager → 13 observation engines → intelligence (rule/bayes/fusion) → execution/
  journal/backtester → runtime/UI/telegram/ignition/risk-analytics → learning/
  agents/LLM-sensor/live-broker/go-live-gates. §25.9 golden path reproduces exactly.

See `git log` for commit-level detail and `specs/STATUS.md` for the current
build state and what's still dormant.
