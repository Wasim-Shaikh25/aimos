# Changelog

Everything implemented, newest first. **Update this file after every change** —
one entry per meaningful unit of work (see `CLAUDE.md`). Format loosely follows
Keep a Changelog. Dates are the working session, not calendar-exact.

## Unreleased

### Added
- **SaaS v2.0 Phase 1 auth foundation** (`aimos/saas/`): SQLAlchemy user/org models,
  bcrypt password hashing, JWT access/refresh tokens with rotation, email
  verification and password reset over SMTP, phone OTP with console/Twilio/Vonage
  pluggable sender, Google + Apple OAuth2 helpers, and `/auth/*` + `/api/v2/*`
  FastAPI routers. Config-driven via `config/saas.yaml` and `AIMOS__SAAS__*`
  env overrides; master switch `features.saas_enabled` (default `false`) keeps the
  single-user path unchanged.
- **Dashboard auth screens and tenant-aware API client** (`dashboard/src/auth.jsx`,
  `dashboard/src/api.js`, `dashboard/src/App.jsx`): login/register/email-verification,
  organization switcher, per-tenant `X-Organization-Id` header, and an
  `/api/v2/status` probe so the dashboard falls back to local mode when SaaS is
  disabled. `npm run build` is green.
- **SaaS v2.0 Phase 2 runtime state + per-tenant journal scaffolding**:
  - `aimos/runtime/state_store.py` persists equity curve, broker state, multi-venue
    balances, positions, go-live ladder, and feature flags across restarts. Saves
    beside the journal for isolated deployments; uses the tenant DB when SaaS is on.
  - `aimos/saas/journal_tenant.py` routes each organization to its own journal.
  - `aimos/saas/state_tenant.py` persists per-tenant runtime state in the auth DB.
  - `PaperBroker` and `MultiVenueSim` gain `state_dict()` / `load_state()` so the
    paper loop can resume after a restart.
  - `runtime/serve.py` loads state at boot and snapshots it every tick.
- **12-month historical dataset downloader** (`scripts/download_history.py`):
  free public Binance Vision monthly klines → `CandleStore` parquet for ML
  training and regression tests. Supports multi-symbol and `1m/5m/15m/1h/4h/1d`.
- **Streaming layer scaffold** (`aimos/data/streaming.py`):
  - `BinanceWebsocketSource` connects to Binance combined websocket streams
    (`@trade`, `@depth`, `@miniTicker`) and normalizes events into a venue-agnostic
    `StreamEvent` shape.
  - `StreamRecorder` writes events to `state/streams/<date>.jsonl` for
    deterministic replay via `RecordedStreamSource`.
  - `runtime/serve.py` starts a `stream_loop()` when `features.streaming_enabled`
    is true; it records but does not yet feed the slow paper loop (Phase 3).
- **SaaS v2.0 requirements and task tracker** (`specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md`):
  roadmap for finishing the remaining runtime pieces (streaming, persistence, dashboard
  charting, ML pipeline, vendor vendoring, 12-month dataset, live multi-venue wiring)
  and adding a self-hostable SaaS layer with Google/Apple/email/phone auth and
  multi-tenant organizations. Designed to use only free/open-source dependencies and
  operator-supplied credentials; no paid third-party services required.
- **OpenAI backend for the AI analyst** — the analyst now supports `assistant.provider:
  openai` (default `gpt-4o-mini`, cheap) alongside Anthropic, selected by config; same
  grounded, read-only prompt, injectable caller (both covered by offline tests). Uses
  `OPENAI_API_KEY`. Config gains `assistant.provider` + `assistant.openai_model`.
- **`specs/DEPLOYMENT.md`** — one end-to-end runbook: run → paper (for months) →
  Telegram → AI analyst (Anthropic/OpenAI) → deploy cheaply (~$5/mo VPS + Docker
  Compose) → testnet validation → train/enable ML → **when and how to go live**
  (the fail-closed ladder + a go/no-go checklist) → emergency stop. Linked from the
  README; `.env.example` gains `OPENAI_API_KEY` + analyst env vars.
- **Read-only AI analyst** (`aimos/runtime/assistant.py`, `specs/ASSISTANT.md`):
  a natural-language assistant — dashboard **AI Analyst** chat screen + Telegram
  `/ask` and `/report` — that answers questions about the running system and
  generates timeframe reports **grounded in the journal + real metrics** (recent
  decisions, performance, ML/model status, monitor coverage, features, go-live,
  equity). It is the sanctioned LLM role (§15.3): strictly read-only, it explains
  and *advises* but cannot trade, flip flags, or edit config — any action it
  recommends goes through the existing CONFIRM-gated controls. The LLM caller is
  injected (plain httpx to the Anthropic Messages API), so grounding/prompting is
  fully tested offline. Off by default (`assistant.enabled` + `ANTHROPIC_API_KEY`),
  on-demand only (never per tick); secrets never enter the prompt.
- **Train the ML on older data via paper replay** (`aimos/learning/dataset.py`,
  `scripts/train_from_history.py`): replays historical candles (Binance-vision CSVs,
  the parquet CandleStore, or offline synthetic) through the exact production
  observation→intelligence pipeline (anti-lookahead), labels every decision with the
  triple-barrier method, and trains a walk-forward-validated logistic model. Feature
  construction is unified with inference via the new `IntelligenceLayer.ml_feature_vector`
  (single source of truth → no train/serve skew). **Enable/disable switch:** off by
  default (`learning.history.enabled`); the trained model is saved in **shadow**
  (fusion weight 0) and the script prints the exact one-line change to enable it —
  and only if it clears the AUC gate. Nothing reaches the decision path until a human
  raises `intelligence.fusion_weights.ml` after the shadow window (§8.3).

### Fixed
- **Decision-path edge cases** found in end-to-end adversarial testing (new
  `tests/test_decision_edge_cases.py`, arb invariant test):
  - **Sizer no longer emits a zero-notional "trade."** An asset already at its
    concentration cap drove the risk-based size to 0, which passed every gate
    (default `min_notional=0`) as a `LONG size_quote=0.0`. The sizer now rejects a
    non-positive or non-finite final size before it reaches the risk manager/broker.
  - **Non-finite geometry can't reach an order.** A NaN/inf price propagated all the
    way to `size_quote=NaN`; the sizer now rejects non-finite entry/stop, and
    `TrendFollowing` no longer emits a plan from a non-finite/≤0 price.
  - **Evaluator drops stop-less / non-finite-EV candidates.** A candidate with no
    usable stop distance had its costs ignored and could win — then get rejected at
    sizing, suppressing a valid trade. Such candidates are now dropped up front.
  - **Multi-venue arb can't drive a venue negative.** The inventory constraint now
    includes the buy-side fee, so a venue never spends USDT it doesn't hold (was
    going negative by the fee amount); total USDT stays conserved.

### Added
- **Feature monitor agent** (`aimos/runtime/monitor_agent.py`): a background self-
  tester that probes every feature on an interval (universe, per-venue prices &
  decisions, engines, cross_exchange, scalp, trades, balances, performance, mind-
  map, connections, go-live) and publishes a coverage report — ok/degraded/failing
  + coverage % — to `/api/monitor`, `state/monitor_report.json`, and a new
  **Monitor** dashboard screen. With `monitor.force_coverage` it flips the safe
  keyless flags (cross_exchange, scalp) on once so every path is exercised without
  waiting for organic conditions — fast, hands-off testing. Never touches
  live/funded features. Off by default (`monitor.enabled`); wired into `serve`.
- **`specs/TESTNET.md`**: step-by-step guide to get free Binance **testnet** keys
  (GitHub SSO, fake funds, real API), wire them via `AIMOS_SECRETS_FILE`/env, arm a
  tiny mandate, and run the live-integration validator — the safe way to prove the
  live path works before risking money, plus the mainnet path and troubleshooting.
- **Live-integration validator** (`aimos/runtime/validate.py`,
  `scripts/validate_integration.py`): runs the real account+order path against an
  exchange **testnet** (free, real API) — authenticate → balance → withdrawals-
  disabled → place tiny order → cancel → reconcile — and prints a PASS/FAIL report,
  marking the go-live testnet gate on all-pass. The safe way to confirm the build
  works against a real exchange before risking money. Mock-tested.

### Fixed
- **`.env` templates**: removed a stale, misleading `BINANCE_API_KEY`/`BINANCE_SECRET`
  block (the code reads `AIMOS_KEY_<VENUE>` / a secrets file, not those names).
  Clarified the exchange-key section and listed all three venues
  (binance / kraken / coinbase) in `.env.example` and `.env.prod.example`.

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
