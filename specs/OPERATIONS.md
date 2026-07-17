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

---

## 5. Account keys (live/account features only — paper needs NONE)

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
