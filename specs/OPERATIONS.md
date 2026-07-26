# OPERATIONS — running, deploying, configuring, going live

**Objective:** everything an operator needs to run AIMOS — quickstart, deployment,
configuration, feature activation, storage, the go-live ladder, and emergency
stop. (Consolidates the former QUICKSTART / ACTIVATION_GUIDE / GO_LIVE / RUNBOOK.)

Paper mode is the default everywhere and needs **no exchange API keys**. Live
trading is behind the §23.8 go-live ladder, `mandate.yaml`, and
withdrawal-disabled keys — see [Go-live](#go-live-ladder-238).

---

## 1. Run it

### One command — full stack (dashboard + paper loop + Telegram)
```bash
./run.sh            # offline synthetic data (no keys, no network)
./run.sh --live     # live PUBLIC candles (needs internet; still no API keys)
```
Open **http://localhost:8000**. Or run the server directly:
```bash
pip install -e '.[serve,data]'
python -m aimos.runtime.serve            # dashboard + paper loop + Telegram, auto-started
```

### Headless paper loop (no dashboard)
```bash
pip install -e .
python -m aimos.runtime.paper_trader --offline --ticks 3   # deterministic, offline
```

### Docker (recommended for a real deployment)
```bash
cp .env.example .env          # set TELEGRAM_BOT_TOKEN etc. (optional)
docker compose up -d          # aimos (dashboard+loop+Telegram) + postgres + watchdog
docker compose --profile commands up -d   # + inbound Telegram command bot (optional)
```
The loop **auto-starts** with the server (FastAPI lifespan) — nothing extra to enable.

---

## 2. Configuration

`config/*.yaml` holds every tunable (initial values, not hardcoded constants).
**Any key is env-overridable**: `AIMOS__SECTION__KEY=value` (double-underscore =
nesting). Key files: `default.yaml`, `observation.yaml`, `universe.yaml`,
`costs.yaml`, `weights.yaml`, `scalp.yaml`, `mandate.yaml`, `config/plugins/*.yaml`.

### Feature flags (`config/default.yaml features:`)
| Flag | Default | Meaning |
|---|---|---|
| `mode` | `paper` | `paper` \| `live` (live requires the ladder) |
| `features.telegram_enabled` | `false` | Telegram alerts (needs `TELEGRAM_BOT_TOKEN`) |
| `features.live_data` | `true` | live public candles (no keys) vs offline synthetic |
| `features.cross_exchange_enabled` | `false` | cross-venue price monitoring + arb (also enable the plugin) |
| `features.scalp_enabled` | `true` | §17 minute-scale scalping |
| `features.llm_news_sensor` | `false` | §19 LLM news sensor (needs `ANTHROPIC_API_KEY`) |
| `features.saas_enabled` | `false` | SaaS auth, orgs, and tenant-aware UI (off keeps single-user mode) |
| `paper.use_universe` | `true` | analyze the discovered/seeded universe (top-N by volume) |
| `paper.max_symbols` | `40` | top-N assets analyzed per tick |
| `paper.cross_venues` | `[binance, kraken]` | venues sampled for cross-exchange work |

Scalp and cross_exchange can also be **toggled at runtime** from the dashboard
**Controls** screen or Telegram (`/enable scalp`, `/disable cross_exchange`) — no
restart. Live/funded flags are LOCKED there.

### Environment files
- `.env.example` → copy to `.env` (dev). `.env.prod.example` → `.env.prod`.
- Real `.env*` are git-ignored; only `*.example` templates are committed.

---

## 3. Storage — where data is saved

| Data | Store | Location |
|---|---|---|
| Decisions, outcomes, evidence, trades (hash-chained) | **SQLite** (the Journal) | `paper.journal_path` → `state/aimos.sqlite` |
| Equity / decisions / prices / trades time-series | **TimescaleDB** (optional) | `AIMOS_TIMESCALE_DSN` |
| Go-live progress | JSON | `state/go_live.json` |
| Auth / tenant metadata | SQLite/Postgres | `config/saas.yaml` `database_url` or `AIMOS__SAAS__DATABASE_URL` |
| Per-tenant journals | SQLite | `state/journals/<org_id>.sqlite` (Phase 2) |
| Recorded market candles | Parquet | data root |
| API secrets | **not stored** | read from `AIMOS_SECRETS_FILE` / env |

The **SQLite journal is the tamper-evident system of record** (SHA-256 chain;
verify with the journal verifier). **TimescaleDB** is optional analytics — enable
with `pip install -e '.[timescale]'` and set
`AIMOS_TIMESCALE_DSN=postgresql://aimos:aimos@postgres:5432/aimos` (docker-compose
wires this to the bundled TimescaleDB service). Empty DSN = off (no-op).

---

## 4. Feature activation — the dormant pieces

Most "off" features are real, tested code gated on a prerequisite (a key, a data
source, capital, or a calibration gate) — not stubs. Enable = flip the flag +
provide the prerequisite + restart (or use the runtime toggle where noted).

| Feature | Turn on with | Prerequisite |
|---|---|---|
| Telegram alerts/commands | `features.telegram_enabled` + `TELEGRAM_BOT_TOKEN` | a bot token |
| Cross-exchange arb | Controls toggle / `features.cross_exchange_enabled` + plugin | — (live fills need balances) |
| Scalping | `features.scalp_enabled` (on) | real fast-loop stream for live |
| LLM news sensor | `features.llm_news_sensor` + `ANTHROPIC_API_KEY` | Anthropic key |
| On-chain engine | provide an `OnchainProvider` | data provider |
| ML fusion weight | `intelligence.fusion_weights.ml > 0` | passes the shadow calibration checklist (§8.3) |
| Live balances | add read-only keys (see §5) | withdrawal-disabled keys |
| Live trading | the go-live ladder (§6) | funded accounts + keys + ladder |

### Feature monitor agent (`config/default.yaml monitor:`)

A background self-tester that probes every feature on an interval and publishes a
coverage report (per-feature ok/degraded/failing + coverage %) to `/api/monitor`,
`state/monitor_report.json`, and the **Monitor** dashboard screen. Off by default.

| Key | Default | Meaning |
|---|---|---|
| `monitor.enabled` | `false` | run the monitor loop in `serve` (env `AIMOS__MONITOR__ENABLED=true`) |
| `monitor.force_coverage` | `true` | enable the safe keyless flags (cross_exchange, scalp) once, to exercise every path fast |
| `monitor.interval_seconds` | `20` | re-probe + republish cadence |

It never touches live/funded features. Use it to shake out the whole system quickly:
`AIMOS__MONITOR__ENABLED=true python -m aimos.runtime.serve`, then watch the Monitor
screen climb toward 100% coverage.

### Train the ML on older data (`scripts/train_from_history.py`)

Replays historical candles as paper trades, labels them (triple-barrier), and
trains a walk-forward logistic model — the disciplined way to build the ML on past
data. **Off by default** (the enable/disable switch); the model is saved in shadow
and only affects decisions after you deliberately raise its fusion weight.

| Key | Default | Meaning |
|---|---|---|
| `learning.history.enabled` | `false` | master switch (env `AIMOS__LEARNING__HISTORY__ENABLED=true`) |
| `learning.history.horizon_bars` | `24` | triple-barrier forward window |
| `learning.history.warmup` | `200` | bars skipped before the first labelled decision |
| `learning.history.n_folds` | `3` | walk-forward validation folds |
| `intelligence.ml_model_path` | `""` | trained artifact the ML engine loads (empty → inert) |
| `intelligence.fusion_weights.ml` | `0.0` | ML's weight in fusion — **the enable/disable for ML** |

```bash
export AIMOS__LEARNING__HISTORY__ENABLED=true
# pick a data source (Binance publishes free klines at https://data.binance.vision/):
python -m scripts.train_from_history --csv 'data/BTCUSDT-1h-*.csv' --symbol BTC/USDT
python -m scripts.train_from_history --parquet --exchange binance --symbol BTC/USDT --timeframe 1h
python -m scripts.train_from_history --synthetic --symbols BTC/USDT,ETH/USDT   # offline demo
```

The script prints the walk-forward AUC vs. the gate (`learning.ml.val_auc_min`) and,
**only if it passes**, the exact two env lines to enable ML
(`AIMOS__INTELLIGENCE__ML_MODEL_PATH=…` + `AIMOS__INTELLIGENCE__FUSION_WEIGHTS__ML=0.15`).
Training needs `learning.ml.min_labeled_samples` (2000) labelled bars and never
auto-enables — you promote it, after watching it in shadow (§8.3).

### Read-only AI analyst (`config/default.yaml assistant:`)

A natural-language analyst — dashboard **AI Analyst** screen + Telegram `/ask` /
`/report` — that answers questions and writes timeframe reports **grounded in the
journal + metrics**. Sensor/explainer only (§15.3): read-only, advisory, it never
trades or changes settings. Off unless enabled **and** `ANTHROPIC_API_KEY` is set.

| Key | Default | Meaning |
|---|---|---|
| `assistant.enabled` | `false` | master switch (env `AIMOS__ASSISTANT__ENABLED=true`) |
| `assistant.model` | `claude-sonnet-5` | Anthropic model id |
| `assistant.max_tokens` | `1200` | response cap |
| `assistant.temperature` | `0.2` | low — analysis, not creativity |
| `assistant.recent_decisions` | `40` | decisions pulled into the grounding bundle |
| `assistant.timeout_seconds` | `40` | LLM call timeout |

```bash
export ANTHROPIC_API_KEY=...            # required
export AIMOS__ASSISTANT__ENABLED=true
# then, in the UI AI Analyst screen or on Telegram:
#   /ask is the ML working?      /report 7d
```

Recommendations are advisory — act on them via Controls / the CONFIRM-gated APIs.
See `specs/ASSISTANT.md` for the grounding design and guardrails.

---

## 5. SaaS authentication and multi-tenancy (optional)

Enable with `features.saas_enabled: true` (or `AIMOS__FEATURES__SAAS_ENABLED=true`)
and install the auth dependencies:

```bash
pip install -e '.[serve,saas]'
```

Auth/tenant data lives in the database configured by `config/saas.yaml`
`database_url` or `AIMOS__SAAS__DATABASE_URL` (defaults to `sqlite:///state/auth.sqlite`).
A 32-byte JWT secret is auto-generated and persisted in `state/.jwt_secret` on first
startup (or set `AIMOS__SAAS__JWT_SECRET` explicitly).

### Operator-supplied credentials

All external auth services are operator-supplied; AIMOS itself uses only
free/open-source libraries.

| Service | Config / env | What for |
|---|---|---|
| SMTP | `config/saas.yaml` `smtp.*` or `AIMOS__SAAS__SMTP__*` | email verification and password reset |
| Google OAuth | `oauth.google.*` or `AIMOS__SAAS__OAUTH__GOOGLE__*` | Sign in with Google |
| Apple Sign In | `oauth.apple.*` or `AIMOS__SAAS__OAUTH__APPLE__*` | Sign in with Apple |
| SMS (optional) | `sms.*` or `AIMOS__SAAS__SMS__*` | phone OTP via Twilio or Vonage |

Phone OTP defaults to **console logging** (code written to `state/smsdrop/`); real
SMS requires operator credentials. When no SMS gateway is available, phone
registration can fall back to email OTP in a future update.

### Endpoints

- `POST /auth/register`, `/auth/login` — email + password.
- `POST /auth/verify-email`, `/auth/resend-verification` — email verification code.
- `POST /auth/forgot-password`, `/auth/reset-password` — password reset.
- `GET /auth/google` → Google consent, `GET /auth/google/callback`.
- `GET /auth/apple` → Apple consent, `POST /auth/apple/callback`.
- `POST /auth/phone/send`, `/auth/phone/verify` — phone OTP.
- `GET /api/v2/me`, `/api/v2/organizations`, `POST /api/v2/organizations`.
- `GET/PATCH /api/v2/config` — per-tenant config overrides (owner/admin).

The dashboard detects SaaS mode via `/api/v2/status`; when SaaS is off it falls
back to the original single-user experience.

### Per-tenant runtime state

SaaS deployments set `AIMOS_RUNTIME_ORG_ID=<org-id>` on the trading process. The
loop uses that org for its journal (`state/journals/<org-id>.sqlite`) and
persists broker state, multi-venue balances, positions, equity curve, go-live
ladder, and feature flags to the tenant DB (`organization_states` table).

Single-user deployments keep the journal at `paper.journal_path` and persist
runtime state to a `tenant_local_state/state.json` file beside the journal. An
in-memory journal (`:memory:`) disables state persistence, which is the default
for tests and short-lived runs.

---

## 6. Account keys (live/account features only — paper needs NONE)

Keys are used **only** for account access (balances, live orders), never for
market-data analysis. Provide them via a secrets file (preferred) or env:
```bash
cp secrets.example.yaml /run/secrets/aimos.yaml   # fill in; withdrawals MUST be off
export AIMOS_SECRETS_FILE=/run/secrets/aimos.yaml
# or: AIMOS_KEY_BINANCE=... AIMOS_SECRET_BINANCE=...
```
On startup the **read-only preflight** authenticates each key, fetches balance,
verifies withdrawals are disabled, and reports on the **Connections** screen —
**no orders are placed**. Secrets are never logged, journaled, or shown in the UI.

---

## 6. Go-live ladder (§23.8)

Real-money trading is **fail-closed** — it unlocks only when *every* gate is signed
off on the **Go-Live** screen (`/golive`, `GET /api/golive`). Time-based gates show
auto progress but still need an explicit sign-off; the app **refuses to boot** in
`mode: live` until all gates pass (`guard_live_boot`).

| # | Gate | Clear it by |
|---|------|-------------|
| 1 | Validated 12-month backtest | permutation p<0.05, bootstrap CI, benchmarks beaten (§9.3/§20.2) |
| 2 | 4 weeks paper | ≥28 days of journaled paper decisions (auto-tracked) |
| 3 | 1 week testnet | `python -m scripts.testnet_order --exchange binance` places one real testnet order + reconciles; run a week |
| 4 | Security signoff + restore drill | withdrawal-disabled keys, backup/restore drill, incident runbook (§23.4/§23.5) |
| 5 | 10% canary | `mode: live`, mandate at 10% caps, 2 weeks, divergence within tolerance |
| 6 | Scale in 25% steps | raise mandate caps, divergence-gated, to full size |

Three independent locks stand between the system and real money: the Controls/
Telegram locks, the fail-closed `mandate.yaml`, and the boot guard.

---

## 7. Start / stop / upgrade / emergency

- **Start:** `docker compose up -d`. **Stop:** `docker compose down` (the journal
  persists; restart reconciliation resolves state).
- **Upgrade:** pull → `docker compose build` → `docker compose up -d`. Vendored
  code is frozen; re-vendoring is a deliberate human-approved event (§22.3).
- **Emergency stop:** dashboard **Positions & Risk → killswitch** (CONFIRM-gated);
  Telegram `/killswitch` (nonce-confirmed); or `touch RUNTIME_HALT` in the working
  dir (loop halts, forces NO_TRADE).
- **Watchdog:** heartbeat at `state/heartbeat`; 3× miss → restart + alert (§23.5).
