# Changelog

Everything implemented, newest first. **Update this file after every change** —
one entry per meaningful unit of work (see `CLAUDE.md`). Format loosely follows
Keep a Changelog. Dates are the working session, not calendar-exact.

## Unreleased

### Removed / Changed (auth surface — operator decision on PD2)
- **Deleted the retired auth surface entirely** (resolves audit finding M1;
  operator's answer to PD2 for the auth-code half): `aimos/saas/oauth.py` and
  `aimos/saas/sms.py` removed; `register_email_password`, `verify_email`,
  `resend_email_verification`, `forgot_password`, `reset_password`,
  `login_email_password`, `send_phone_verification`, `verify_phone_and_login`,
  `login_with_google`, `login_with_apple`, and the dead `set_auth_cookies` removed
  from `aimos/saas/auth_service.py` / `router.py`. Removed the now-unused
  `UserIdentity`, `EmailVerificationCode`, `PasswordResetToken`,
  `PhoneVerificationCode` ORM models and the `oauth`/`sms` config blocks from
  `SaasConfig`. Dropped `Authlib` from `pyproject.toml`.
- **The only login flow is now email + password + email OTP** — no phone/SMS
  login, no Google/Apple OAuth, no self-service password reset. Nothing dormant
  remains to audit or accidentally re-expose. `admin.phone` is kept as an
  informational profile field only (returned by `/api/v2/me`), not a login path.
  Verified: all 26 `test_saas.py` tests pass unchanged (the surface was fully
  dead — zero test coverage of it existed), and a live end-to-end login
  (password → OTP → token) still works after the removal.
- **Documented [Brevo](https://www.brevo.com) as the recommended SMTP provider**
  for the login OTP (`config/saas.yaml`, `specs/OPERATIONS.md`) — free-tier SMTP
  relay, no code change since `email.py` already speaks plain SMTP.
- Corrected a stale `specs/STATUS.md` line: runtime state (equity/balances/
  broker/sim/ladder) already persists across restarts via `RuntimeStateStore`
  (wired into `serve.py`'s boot/save loop) — it was listed as not-built.
- **New `specs/REQUIREMENTS_BACKLOG.md`** — 19 prioritized requirements
  consolidating the production-readiness audit's residual items (M2–M9, PD1/PD3/
  PD5, Group 3/4 remediation items) with a competitive-feature review against
  TradingAgents (Tauric Research) and the OpenBB Platform. Notably: REQ-1 (wire
  the already-built, already-tested `risk/analytics.py` alpha/beta/VaR-ES to an
  API endpoint and the dashboard — currently unreachable) and REQ-11 (formalize a
  no-copyleft-in-`aimos/` dependency policy, since OpenBB is AGPLv3 and the
  network-use clause would apply if it were ever imported directly).

### Security / Fixed (audit remediation)
- **C1 (Critical) — SPA path traversal closed.** `runtime/serve.py` now resolves the
  requested path and serves a file only when it is inside `dashboard/dist`
  (`is_relative_to`), else returns the SPA shell. Verified live: `…/state/.jwt_secret`,
  `…/config/mandate.yaml`, `…/CLAUDE.md` all return the shell, not the file.
- **C2 (Critical) — dashboard reachable with auth on.** `api/server.py` middleware
  exemption rewritten (`_is_public_path`): the SPA shell + `/assets/*` are public,
  `/api/*` and `/metrics` stay token-gated. Verified live + login page renders in a
  browser under SaaS.
- **H1 — control API hardened.** Default `AIMOS_HOST` is now `127.0.0.1`; control and
  assistant endpoints refuse non-loopback callers when SaaS is off.
- **H2 — OTP no longer leaked.** The no-SMTP log no longer includes the email body;
  `state/maildrop` / `state/smsdrop` are opt-in via `AIMOS_DEV_MAILDROP` and written
  `0600`. Fixed a `NameError` in `_render_password_reset_email`.
- **H3 — auth brute force bounded.** Login codes are burned after 5 wrong guesses
  (`EmailLoginCode.attempts`); `/auth/*` is rate-limited per client (429).
- **M8 — atomic state writes.** New `runtime/atomic_io.py` (temp + fsync + rename);
  `state_store.load` tolerates a torn file; `golive` keeps a `.bak` and restores it.
- **H4 — journal backups.** New `scripts/backup_journal.py` — SQLite online-backup
  API (consistent under writes) + immediate hash-chain verify + retention + an
  atomic `journal-latest.sqlite` pointer. `scripts/restore_drill.sh` now **exits 1**
  when no backup exists (a drill with no backup is not a pass).
- **H5 — CI.** New `.github/workflows/ci.yml` runs pytest + all three lints + the
  GPL tripwire + a backup/restore drill, plus a dashboard-build job, on every
  push/PR so the gates are enforced rather than discipline-only.
- **L5 — accessibility.** `dashboard/index.html` sets `<html lang="en">`.
- Suite grew 466 → **488 passed / 1 xfailed**; magic-number, naive-datetime, and
  import-linter (6/6) gates remain green. **All Critical/High/Medium audit blockers
  are now fixed**; recommendation moves to **STOP — CONDITIONAL GO** (conditional on
  an independent verification pass + product decisions PD1–PD5).

### Added
- **REQ-1 — wired `aimos/risk/analytics.py` to a live endpoint and the dashboard.**
  New `aimos/risk/analytics_runner.py` fetches BTC + equal-weight T1-basket returns,
  aligns them with the equity curve, and computes VaR/ES (95%/99%), alpha/beta + t-stat
  vs both benchmarks, and the BTC-beta / idiosyncratic factor split. A daily
  APScheduler job in `runtime/serve.py` caches the report; `GET /api/risk` serves it
  (and computes on demand when empty). `PositionsRisk.jsx` renders the stress panel
  and `Performance.jsx` shows alpha/beta attribution. Config added to `config/default.yaml`
  (`risk.enabled`, `interval_seconds`, `timeframe`, `min_samples`); tests in
  `tests/test_risk_analytics_api.py`.
- **`PRODUCTION_READINESS_AUDIT.md`** — end-to-end product and production-readiness
  audit at commit `5fd1b88`. Audit-only; **no application source was modified**.
  18 findings (2 Critical, 5 High, 7 Medium, 4 Low); recommendation **CONTINUE — NO-GO**.
  Baseline recorded: 466 passed / 1 xfailed, magic-number + naive-datetime lints
  clean, import-linter 6/6, GPL tripwire armed (2 files).
  - **C1 (Critical)** — unauthenticated path traversal in the SPA catch-all
    (`runtime/serve.py:892`): percent-encoded `../` escapes `dashboard/dist` and
    serves `state/.jwt_secret`, `state/.settings_key`, `state/maildrop/*`,
    `secrets.yaml`, `.env`, `/etc/passwd`. Reproduced by execution.
  - **C2 (Critical)** — enabling `saas_enabled` makes the dashboard, its login page,
    and `/assets/*` return 401 (`api/server.py:111` exemption list omits non-API
    paths), so auth cannot be switched on. Reproduced by execution.
  - **H1** — control API (killswitch, feature toggles, go-live sign-off, LLM
    assistant) is unauthenticated when `saas_enabled` is false (the default).
  - **H2** — login OTPs logged at WARNING and written unconditionally to
    `state/maildrop/` in plaintext, violating the "secrets are never logged" rule.
  - **H3** — no inbound rate limiting or lockout; OTP codes are not invalidated on
    failed attempts; 275 ms of bcrypt per unauthenticated request is a DoS vector
    against the process that also runs the trading loop.
  - **H4** — no backup mechanism exists and `scripts/restore_drill.sh` exits 0 when
    no backup is found.
  - **H5** — no CI/CD; the four documented quality gates are unenforced.
  - **Pass 2 (live-server execution):** built the dashboard and ran the real app.
    C1 confirmed against the running server and the full kill chain proven
    (traversal → leak `state/.jwt_secret` → forge a token that `decode_token`
    accepts as admin). Dashboard renders (21 screens, 0 console errors); no XSS
    sink exists; the Telegram channel verified as a genuine strength. Added **M8**
    (non-atomic `state.json`/`go_live.json` writes — torn write crashes boot or
    silently wipes go-live sign-offs, both reproduced) and **L5** (`<html>` missing
    `lang`). **No new Critical/High** — recommendation unchanged at **NO-GO**.

### Changed
- **Single-admin mode + email OTP 2FA** (`aimos/saas/`):
  - Removed public registration, Google/Apple OAuth, phone OTP, and forgot-password
    endpoints; the only auth flow is admin login.
  - Admin credentials (user_id, email, phone, password) are seeded from
    `config/saas.yaml` `admin.*` or `AIMOS__SAAS__ADMIN__*` env vars and hashed on
    first run.
  - Login is two-step: `/auth/login` verifies the password and sends a one-time
    code to the admin email; `/auth/login/verify` validates the code and issues
    JWT access/refresh tokens.
  - Dashboard `auth.jsx` and `api.js` updated for the new flow.

### Docs
- Updated `README.md`, `specs/OPERATIONS.md`, `specs/DEPLOYMENT.md`,
  `specs/STATUS.md`, `.env.example`, `.env.prod.example`, and
  `specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md` to describe the
  single-admin auth model, email OTP 2FA, encrypted `SettingsStore`, and the
  `/api/v2/settings` control plane. Removed references to the retired
  multi-user/multi-tenant SaaS design.

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
- **Dashboard charting + screens**:
  - `dashboard/src/components/EquityChart.jsx` — `lightweight-charts` line chart
    on the Performance screen, driven by `/api/equity`.
  - `dashboard/src/components/CandlestickChart.jsx` + `dashboard/src/screens/Candles.jsx`
    — OHLC candlestick chart with per-venue selector, driven by the new
    `/api/candles/{symbol}` endpoint.
  - Evidence tables remain on `Engines`, decision anatomy flow on `DecisionAnatomy`,
    and the new `Settings` screen handles members/invites.
- **Dashboard auth screens completed** (`dashboard/src/auth.jsx`):
  login, registration, email verification, forgot-password/reset, and phone-OTP
  sign-in are now wired to the SaaS auth endpoints.
- **Dashboard settings / organization screen** (`dashboard/src/screens/Settings.jsx`):
  lists organization members, sends invites by email/role, and displays per-tenant
  config overrides. Routes and API helpers added to `App.jsx` and `api.js`.
- **Tenant members + invite tests** (`tests/test_saas.py`):
  covers `GET /api/v2/organizations/{id}/members` and `POST .../invite`.
- **Test coverage for v2.0 modules`:
  - `tests/test_runtime_state.py` — roundtrip save/load of equity, broker, and
    multi-venue balances.
  - `tests/test_model_registry.py` — registry append, promote, demote, drift.
  - `tests/test_streaming.py` — `StreamRecorder` JSONL output and Binance trade
    normalization.
  - `tests/test_migrate_to_saas.py` — single-user → tenant migration.
  - `tests/test_download_history.py` — ZIP CSV parsing and timeframe helpers.
  - `tests/test_vendor.py` — manifest validity, vendoring script dry-run, vendor
    module importability, GPL tripwire presence, and the runtime-import ban on
    `vendor.vt_research`.
  - `tests/test_live_multi_venue_wiring.py` — fail-closed live-router construction
    (no keys, incomplete ladder, missing credentials) and `_maybe_arb` routing
    with mock `LiveBroker` legs + unwind detection.
- **ML model registry + promotion/demotion hooks** (`aimos/learning/registry.py`):
  `scripts/train_from_history` now records every run (AUC, Brier, status) to
  `state/model_registry.json`, checks Brier degradation for auto-demotion, and
  prints the exact config lines to enable the model in shadow only after the AUC
  gate passes. The ML fusion weight stays fail-closed at 0 until a human raises it.
- **12-month historical dataset downloader** (`scripts/download_history.py`):
  free public Binance Vision monthly klines → `CandleStore` parquet for ML
  training and regression tests. Supports multi-symbol and `1m/5m/15m/1h/4h/1d`.
- **Per-tenant config overlay + runtime tenant context** (`aimos/saas/config_tenant.py`):
  deep-merges organization-specific overrides from `OrganizationConfig` into the
  base `Params` tree at runtime; `runtime/serve.py` now boots with
  `load_params_for_org(AIMOS_RUNTIME_ORG_ID)` and routes journal/state to the
  per-tenant paths.
- **SaaS org-scoping middleware** (`aimos/api/server.py`):
  trading endpoints (`/api/*` outside `/api/v2/*`) require a valid access
  token whose `org` claim matches `X-Organization-Id` and `AIMOS_RUNTIME_ORG_ID`
  when SaaS is enabled; tenant routes still use `TenantContext`.
- **Vendor vendoring scaffolding** (`scripts/vendor.py`, `vendor/manifest.yaml`):
  reproducible vendoring at pinned SHAs for all six `vendor/` packages with a
  `--dry-run` / `--apply` workflow; `vendor/VENDOR.md` is updated with the pinned
  SHAs and notes which packages still need exact-path / import-rewrite review.
- **Live multi-venue executor wiring** (`runtime/serve.py`):
  `_build_live_router` constructs a `MultiVenueLiveRouter` only when every gate is
  open (`features.multi_venue_live`, `mode=live` or `mandate.enabled`, a complete
  go-live ladder, and per-venue API keys from the secrets file). `_maybe_arb` now
  routes cross-venue arbs through live brokers when the router is present, otherwise
  it stays on the paper simulator. No keys are required or enabled by default.
- **Candlestick API** (`/api/candles/{symbol}`):
  `runtime/serve.py` stores per-venue OHLC DataFrames each tick and exposes them
  as `{time, open, high, low, close}` candle arrays for the dashboard chart.
- **Deployment packaging for SaaS**:
  - `Dockerfile` multi-stage build (Node dashboard + Python runtime) installing
    `[serve,saas,data]` extras; `docker-compose.yml` now passes the shared
    Postgres DSN to `AIMOS__SAAS__DATABASE_URL` so the tenant/auth DB can run
    on the same TimescaleDB container.
  - `scripts/migrate_to_saas.py` migrates an existing single-user deployment to
    a default tenant (`local`), copies `state/aimos.sqlite` to the per-tenant
    journal path, and optionally creates an owner user.
- **Streaming layer** (`aimos/data/streaming.py`, `aimos/data/stream_feed.py`):
  - `BinanceWebsocketSource` connects to Binance combined websocket streams
    (`@trade`, `@depth`, `@miniTicker`) and normalizes events into a venue-agnostic
    `StreamEvent` shape.
  - `StreamRecorder` writes events to `state/streams/<date>.jsonl` for
    deterministic replay via `RecordedStreamSource`.
  - `StreamFeed` converts live `@depth` and `@trade` events into `BookAggregate`
    and `LargePrint` objects and injects them into the slow paper loop's
    `MarketContext` when `features.streaming_enabled` is true.
  - Configurable via the new `streaming` section in `config/default.yaml`.
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
