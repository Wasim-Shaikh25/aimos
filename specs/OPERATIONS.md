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

### Coolify / Docker PaaS

Build context: `.` · Dockerfile: `Dockerfile` · command: `python -m aimos.runtime.serve`.

Set these in the PaaS environment UI:

| Variable | Default | Purpose |
|---|---|---|
| `AIMOS_ADMIN_USERNAME` | `admin` | dashboard login username |
| `AIMOS_ADMIN_PASSWORD` | *(none)* | dashboard login password (required) |
| `AIMOS__MODE` | `paper` | `paper` or `live` (live requires the §23.8 ladder) |
| `AIMOS_HOST` | `127.0.0.1` | bind address; set `0.0.0.0` in containers |
| `AIMOS_PORT` | `8000` | server port (`PORT` is used as a fallback for Coolify) |
| `AIMOS__STORAGE__DATABASE_URL` | *(SQLite)* | optional PostgreSQL/SQLite URL |
| `TELEGRAM_BOT_TOKEN` | *(none)* | optional Telegram alerts/commands |
| `ANTHROPIC_API_KEY` | *(none)* | optional LLM news sensor / AI analyst |

Mount persistent storage for `/app/state`, `/app/data`, and `/app/secrets` so the
journal, backups, and generated auth keys survive container restarts. If you use a
managed PostgreSQL database via `AIMOS__STORAGE__DATABASE_URL`, the journal,
state, controls, model registry, and encrypted user settings are stored there.

The server reads `AIMOS_PORT` first, then `PORT` (many PaaS platforms expose the
chosen port as `PORT`). The Dockerfile healthchecks `/healthz` on that port.

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
| Operational DB (journal + state + controls + model registry) | **PostgreSQL/SQLite** (optional) | `storage.database_url` or `AIMOS__STORAGE__DATABASE_URL` |
| Decisions, outcomes, evidence, trades (hash-chained) | **SQLite** fallback | `paper.journal_path` → `state/aimos.sqlite` when no DB URL |
| Equity / decisions / prices / trades time-series | **TimescaleDB** (optional) | `storage.timescale_dsn`, or defaults to `storage.database_url` |
| Go-live progress | JSON | `state/go_live.json` |
| User settings / auth metadata | SQLite/Postgres | unified `storage.database_url` (`user_settings` table) |
| Runtime config overrides | SQLite/Postgres | `user_settings.config` JSON column, edited via the Settings UI |
| Recorded market candles | Parquet | data root |
| API secrets | **encrypted** | `user_settings.secrets` JSON column, managed through `/api/v2/settings/exchange` |

**Single-DB mode:** set `storage.database_url` to a PostgreSQL (or SQLite) URL
and the journal, runtime state, controls, model registry, and user settings are
all stored in that database, making server swaps or restarts a connection-string
change. The SQLite journal remains the tamper-evident fallback when no URL is
configured.

**Authentication** is single-user via environment:
- `AIMOS_ADMIN_USERNAME` (default `admin`) and `AIMOS_ADMIN_PASSWORD` are checked
  by `/auth/login`.
- `AIMOS_JWT_SECRET` is optional; if unset a secret is generated and saved under
  `~/.aimos/secrets/.jwt_secret`.

**TimescaleDB** is optional analytics — install with `pip install -e '.[timescale]'`;
it defaults to the same URL as `storage.database_url` when `timescale_dsn` is empty.

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

### Risk analytics (`config/default.yaml risk:`)

A daily APScheduler job computes a cached risk report from the equity curve,
BTC returns, and an equal-weight T1 basket.  Served at `/api/risk` and rendered on
the **Positions & Risk** stress panel and **Performance** alpha/beta tiles (REQ-1).

| Key | Default | Meaning |
|---|---|---|
| `risk.enabled` | `true` | run the daily risk-analytics job |
| `risk.interval_seconds` | `86400` | recompute cadence (env `AIMOS__RISK__INTERVAL_SECONDS`) |
| `risk.timeframe` | `""` | benchmark candle timeframe; falls back to `paper.timeframe` |
| `risk.min_samples` | `30` | minimum equity-return samples before computing metrics |

Disable with `AIMOS__RISK__ENABLED=false` if you do not want the scheduler job.

### Health probes (`/healthz`, `/readyz`)

Public liveness/readiness endpoints (REQ-6), exempt from login:
- `GET /healthz` — returns 200 `{"status":"ok"}` whenever the process responds.
- `GET /readyz` — returns 200 only when the journal is writable **and** the paper
  loop heartbeat is fresher than `health.heartbeat_stale_seconds`; otherwise 503.

| Key | Default | Meaning |
|---|---|---|
| `health.heartbeat_stale_seconds` | `30` | max age of the loop heartbeat for `/readyz` to be 200 |

`docker-compose.yml` wires `healthz` into the `aimos` service healthcheck.

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

## 5. Single-user authentication and settings

Authentication is required for the dashboard. Credentials are supplied through the
environment and checked by `/auth/login`.

| Variable | Default | Purpose |
|---|---|---|
| `AIMOS_ADMIN_USERNAME` | `admin` | login username |
| `AIMOS_ADMIN_PASSWORD` | *(none)* | login password (required) |
| `AIMOS_JWT_SECRET` | generated | 32-byte JWT HS256 key |
| `AIMOS_SECRETS_DIR` | `~/.aimos/secrets` | directory for `.jwt_secret` and `.settings_key` |

Install the auth/settings dependencies:

```bash
pip install -e '.[serve,runtime,data]'
```

User settings and encrypted exchange API keys live in the unified database
(`user_settings` table). If `storage.database_url` is empty, a local SQLite file is
used. The JWT secret and settings Fernet key are generated and persisted under
`AIMOS_SECRETS_DIR` on first start.

**No SMTP, OTP, or registration** is exposed. Password changes are made by updating
`AIMOS_ADMIN_PASSWORD` in the environment and restarting.

**Bind host & port.** `python -m aimos.runtime.serve` binds **`127.0.0.1:8000`** by
default (never publicly reachable by accident). Set `AIMOS_HOST=0.0.0.0` — behind a
VPN/SSH tunnel or an authenticated reverse proxy — to bind all interfaces. The Docker
image sets `0.0.0.0` because Compose already publishes only `127.0.0.1:8000` on the
host. The server uses `AIMOS_HOST` (default `127.0.0.1`) and honors `AIMOS_PORT`
first, then `PORT` (the standard variable for PaaS platforms such as Coolify).
Control
endpoints (`/api/control/*`, `/api/assistant`) accept loopback callers without a token;
remote callers must supply a valid `Authorization: Bearer <token>`.

### Endpoints

- `POST /auth/login` — verify username/password and receive an access token.
- `POST /auth/refresh`, `POST /auth/logout` — token rotation and logout.
- `GET /api/v2/me` — current admin user.
- `GET /api/v2/settings` — effective single-user config + exchange metadata.
- `PATCH /api/v2/settings/config` — update config overrides.
- `POST /api/v2/settings/exchange`, `DELETE /api/v2/settings/exchange/{venue}` —
  add/remove encrypted exchange API keys.

### Runtime state

The loop uses `AIMOS_RUNTIME_ORG_ID=local` and stores broker state, multi-venue
balances, positions, equity curve, go-live ladder, and feature flags in the
unified `storage.database_url` (or local JSON files as a fallback). The journal is
at `paper.journal_path` when no database URL is configured.

### API requests

Protected endpoints require an `Authorization: Bearer <token>` header. The
dashboard's `api.js` sends this automatically after login. Control endpoints
(`/api/control/*`, `/api/assistant`) also accept loopback callers without a
token.

---

## 6. Account keys (live/account features only — paper needs NONE)

Keys are used **only** for account access (balances, live orders), never for
market-data analysis. Add them through the **Settings** UI
(`/api/v2/settings/exchange`); they are encrypted at rest with the Fernet key in
`~/.aimos/secrets/.settings_key` (or `AIMOS_SECRETS_DIR/.settings_key`) and are
never logged, journaled, or shown in the UI. For local/headless runs they can
still be provided via env:
```bash
export AIMOS_KEY_BINANCE=... AIMOS_SECRET_BINANCE=...
```
On startup the **read-only preflight** authenticates each key, fetches balance,
verifies withdrawals are disabled, and reports on the **Connections** screen —
**no orders are placed**.

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
- **Upgrade:** pull → `docker compose build` → `docker compose up -d`.
  Vendored code is frozen; re-vendoring is a deliberate human-approved event (§22.3).
- **Database schema:** SQLAlchemy tables are created automatically on first use. No
  Alembic migrations are currently required.
- **Emergency stop:** dashboard **Positions & Risk → killswitch** (CONFIRM-gated);
  Telegram `/killswitch` (nonce-confirmed); or `touch RUNTIME_HALT` in the working
  dir (loop halts, forces NO_TRADE).
- **Watchdog:** heartbeat at `state/heartbeat`; 3× miss → restart + alert (§23.5).

### Network exposure model

AIMOS defaults to **loopback-only** (`AIMOS_HOST=127.0.0.1`). This is the safe
configuration for a single-operator machine or a deployment behind a trusted
reverse proxy / VPN on the same host.

- **Control endpoints** (`/api/control/*`, `/api/assistant/*`) refuse non-loopback
  callers that do not supply a valid `Authorization: Bearer <token>` header.
  `/healthz` and `/readyz` are public for load-balancer probes.
- **External reach:** use an authenticated reverse proxy (mTLS or a VPN) on the
  same trust boundary. AIMOS does not terminate public TLS itself.

### Backups & restore (§23.5)

The hash-chained journal (`state/aimos.sqlite`) is the system of record — back it up.

**Default RPO/RTO:**
- **RPO = 1 hour** — the runtime schedules an APScheduler job (`journal_backup`)
  that creates a verified snapshot every 3600 seconds.
- **RTO = manual restore from latest** — `backups/journal-latest.sqlite` is an
  atomic pointer to the most recent verified snapshot; restart with that file
  as `paper.journal_path`.

```bash
# Create a verified, consistent snapshot (SQLite online-backup API; verifies the
# hash chain before accepting it) and update backups/journal-latest.sqlite.
python scripts/backup_journal.py --src state/aimos.sqlite --dest backups --keep 14

# Monthly restore DRILL — restores the latest backup and re-verifies the chain.
# Exits non-zero if there is no backup (a drill with no backup is not a pass).
bash scripts/restore_drill.sh
```

Tuning: `config/default.yaml` `backup.*` or env `AIMOS__BACKUP__INTERVAL_SECONDS`,
`AIMOS__BACKUP__DEST`, `AIMOS__BACKUP__KEEP`. The job runs in
`aimos/runtime/serve.py` and uses `aimos.journal.backup.backup_journal` with the
per-tenant journal path.

Back up **separately and securely**: the unified database
(`storage.database_url` or `state/aimos.sqlite` as fallback) and
`~/.aimos/secrets/.settings_key` (or `AIMOS_SECRETS_DIR/.settings_key`) — without
the key, encrypted exchange credentials are unrecoverable. Never drop the settings
key into `backups/` alongside the journal; treat it as a secret.
