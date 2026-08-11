# AIMOS — AI Market Operating System

Autonomous crypto market-intelligence and trading system. Three deterministic
layers — **Observation → Intelligence → Execution** — plus learning, agents, and
institutional-grade risk controls. Stablecoin-quoted pairs only. Paper trading
runs with **no API keys**; live trading is behind a deliberate go-live ladder.

Private project.

---

## Quickstart (paper, no keys)

```bash
./run.sh                 # install + build + serve dashboard & paper loop → http://localhost:8000
# or:
pip install -e '.[serve,data]'
python -m aimos.runtime.serve
```

Everything runs on public/synthetic data with no keys. For the full journey —
paper → Telegram/AI analyst → cheap always-on deploy → testnet → ML → go-live —
follow **[specs/DEPLOYMENT.md](specs/DEPLOYMENT.md)** (and
**[specs/OPERATIONS.md](specs/OPERATIONS.md)** for the config reference).

## What you get, day one (all paper)

- The full decision engine: 13 observation engines → rule/bayes/ML fusion →
  execution plugins, with a hash-chained audit journal.
- **Multi-platform analysis** across binance/kraken/coinbase, a live price matrix,
  and simulated cross-venue arbitrage + scalping.
- A live-polling **dashboard**: markets, prices, decision **mind-map**, engines,
  strategies, models, universe, trade history, balances, connections, controls,
  go-live progress, performance.
- **Telegram** alerts + commands, runtime feature toggles, and a go-live tracker.

## What you must add for more

| To enable | Add |
|---|---|
| Deploy on Coolify / PaaS | see **Deploy on Coolify** below |
| Telegram alerts/commands | a bot token (`TELEGRAM_BOT_TOKEN`) |
| LLM news sensor | `ANTHROPIC_API_KEY` |
| TimescaleDB time-series | `pip install -e '.[timescale]'` + `AIMOS_TIMESCALE_DSN` |
| Live balances / account | read-only, **withdrawal-disabled** keys (see `secrets.example.yaml`) |
| **Live trading** | funded accounts + keys + the **go-live ladder** (§23.8) |
| **Single-user login / settings UI** | `AIMOS_ADMIN_USERNAME` + `AIMOS_ADMIN_PASSWORD` |

Paper trading and price monitoring need **none** of these. Details in
[specs/OPERATIONS.md](specs/OPERATIONS.md).

---

## Deploy on Coolify (or any Docker PaaS)

Build context: `.` · Dockerfile: `Dockerfile` · command: `python -m aimos.runtime.serve`.

### 1. Required environment variables (set in the PaaS UI)

| Variable | Default | Purpose |
|---|---|---|
| `AIMOS_ADMIN_USERNAME` | `admin` | dashboard login username |
| `AIMOS_ADMIN_PASSWORD` | *(none)* | dashboard login password (**required**) |
| `AIMOS__MODE` | `paper` | `paper` or `live` (live requires the go-live ladder) |
| `AIMOS_HOST` | `127.0.0.1` | bind address; set `0.0.0.0` in containers |
| `AIMOS_PORT` | `8000` | server port (`PORT` is used as a fallback for Coolify) |
| `AIMOS__STORAGE__DATABASE_URL` | *(SQLite)* | optional PostgreSQL/SQLite URL for journal + state + settings |
| `AIMOS__FEATURES__LIVE_DATA` | `true` | fetch live public candles (no keys) |
| `TELEGRAM_BOT_TOKEN` | *(none)* | optional Telegram alerts/commands |
| `ANTHROPIC_API_KEY` | *(none)* | optional LLM news sensor / AI analyst |

Set **only** non-secret values in the Coolify env UI. Exchange API keys are entered
later through the Settings UI and encrypted at rest; do not paste them into env
vars unless you are using the legacy `AIMOS_KEY_*` / `AIMOS_SECRET_*` vars.

### 2. Persistent storage

Mount persistent volumes so data survives container restarts:

| Container path | What lives there |
|---|---|
| `/app/state` | journal, runtime state, go-live progress, backups |
| `/app/data` | recorded candles / parquet |
| `/app/secrets` | generated `.jwt_secret` and `.settings_key` |

If you provide `AIMOS__STORAGE__DATABASE_URL` pointing to a managed PostgreSQL
database, the journal, runtime state, controls, model registry, and encrypted
settings all live there — but `/app/state` is still useful for `go_live.json`,
backups, and the generated key files.

### 3. Port & healthcheck

The container honors `AIMOS_PORT` first, then `PORT`. If Coolify auto-sets
`PORT=3000` (or any other value), the server will listen on that port. The
Dockerfile exposes `8000` and includes a `HEALTHCHECK` against `/healthz`.

Point Coolify's healthcheck / domain to:
```
http://<domain-or-container>:<PORT>/healthz
```
The dashboard static files and API are served on the same port.

### 4. First run

After the container starts, open the domain and log in with the credentials from
`AIMOS_ADMIN_USERNAME` / `AIMOS_ADMIN_PASSWORD`. You are in **paper mode** by
default — no exchange keys are needed to see prices, decisions, and simulated
trades. Add real API keys later in **Settings > Exchanges** only when you intend
to move toward live trading through the go-live ladder.

---

## Where data is saved

- **SQLite** — the hash-chained decision/trade journal (`state/aimos.sqlite`), the
  system of record.
- **TimescaleDB** (optional) — equity/decisions/prices/trades time-series.
- **Parquet** — recorded market candles. **JSON/text** — go-live progress, heartbeat.
- **Settings** — runtime config overrides and encrypted exchange API keys live in
  `user_settings` (`state/auth.sqlite` by default) and are edited through the
  Settings UI.
- **Secrets are never logged or returned to the UI** — exchange keys can be
  entered in the dashboard and are encrypted at rest.

## Safety model

Real-money trading is fail-closed behind **three independent locks**: the UI/
Telegram controls refuse to flip live flags; `mandate.yaml` is fail-closed; and the
app **refuses to boot** in live mode until every go-live gate is signed off. The
LLM is a sensor/explainer only — **never** in the decision or control path (§15.3).

## Documentation

| File | Purpose |
|---|---|
| **[specs/DEPLOYMENT.md](specs/DEPLOYMENT.md)** | End-to-end runbook: run → paper → Telegram/AI analyst → deploy cheaply → testnet → ML → go-live (when & how). |
| **[specs/ARCHITECTURE.md](specs/ARCHITECTURE.md)** | The build contract / design spec (every module, formula, threshold; §N references). |
| **[specs/OPERATIONS.md](specs/OPERATIONS.md)** | Run, deploy, configure, activate features, storage, go-live, emergency stop. |
| **[specs/TESTNET.md](specs/TESTNET.md)** | Validate the live path against Binance testnet (free) before real money. |
| **[specs/ASSISTANT.md](specs/ASSISTANT.md)** | The read-only AI analyst — grounding, guardrails, providers. |
| **[specs/STATUS.md](specs/STATUS.md)** | What's built, what's dormant, what's next. |
| **[specs/REQUIREMENTS_BACKLOG.md](specs/REQUIREMENTS_BACKLOG.md)** | Robustness/security/ops backlog — audit residuals + competitive review, prioritized. |
| **[PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md)** | Full security/product audit, findings, and remediation status. |
| **[specs/MODELS.md](specs/MODELS.md)** | Model risk register. |
| **[CHANGELOG.md](CHANGELOG.md)** | Chronological record — updated after every change. |
| `CLAUDE.md` / `.cursor/rules/` | Assistant rules: read STATUS + CHANGELOG first, update the changelog after. |
| `vendor/VENDOR.md`, `vendor/GPL_TRIPWIRE.md` | Vendored-code provenance + license tripwire. |

## Development

```bash
pip install -e '.[dev,data,serve]'
python -m pytest                      # test suite
python scripts/check_magic_numbers.py # decision-path tunable lint
python scripts/check_no_naive_datetime.py
lint-imports                          # layer import direction
```
Hard rules (enforced): contracts-only between layers, no hardcoded tunables in the
decision path, all time via `clock.now()`, no LLM in the decision path.
