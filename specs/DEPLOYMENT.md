# DEPLOYMENT — run it, everything, in order

**Objective:** one place that takes you from a fresh clone to a running system and,
eventually, to gated live trading. Ordered by the journey you actually take:
**run → paper → assistant/Telegram → deploy cheaply → testnet → ML → go-live.**
Deeper references: `specs/OPERATIONS.md` (config), `specs/TESTNET.md` (testnet),
`specs/ASSISTANT.md` (AI analyst).

> Mental model: **one process** (`aimos.runtime.serve`) = API + dashboard + paper
> loop + Telegram, on one port. Paper needs **no keys**. Keys are only for account
> features (balances, live orders) and the optional AI analyst. Everything worth
> keeping lives in `state/` (the SQLite journal is the system of record).

---

## 0. Prerequisites

- Python 3.11+, and Node 18+ if you want the dashboard UI built.
- `git clone` the repo; `cd` into it.

---

## 1. Run it (paper, local) — 1 command

```bash
./run.sh              # offline synthetic data — no keys, no network
./run.sh --live       # live PUBLIC candles — needs internet, still NO API keys
```

Open **http://localhost:8000** — dashboard + API on the same port. That's paper
trading: real (or synthetic) market data → the full observe→decide→execute
pipeline → simulated fills, every decision written to the hash-chained journal.

Manual equivalent (if you don't use `run.sh`):

```bash
pip install -e '.[serve]'                 # add '.[data]' for live candles
(cd dashboard && npm install && npm run build)
python -m aimos.runtime.serve             # http://0.0.0.0:8000
```

Bounded run (stop after N ticks, e.g. for a quick check): `AIMOS__PAPER__MAX_TICKS=50`.

---

## 2. How to run paper (what to actually do for months)

Paper **is** the default — leave it running. The point of the paper phase is to
accumulate enough journaled decisions and outcomes to judge whether there's an
edge. Recommended:

- Run with `--live` (real public candles) on a small always-on host (see §5).
- Turn on the **feature monitor** to keep every path exercised and get a coverage
  report: `AIMOS__MONITOR__ENABLED=true`.
- Watch the dashboard: **Performance**, **Decisions**, **Trade History**, **Balances**.
- Let it run for **months**. This is the single most important step — it's how the
  edge gets proven (or disproven) before any money is at risk. There is no shortcut.

Persist the journal (already the default): `paper.journal_path = state/aimos.sqlite`.
Optional Postgres/TimescaleDB time-series (see §5 Docker).

---

## 3. Telegram (alerts + control + `/ask`)

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the
   **bot token**.
2. Get your **chat id**: message your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id`.
3. Set env and enable:

```bash
export TELEGRAM_BOT_TOKEN="123456:abc..."
export TELEGRAM_ALLOWED_IDS="<your_chat_id>"   # comma-separated whitelist
export AIMOS__FEATURES__TELEGRAM_ENABLED=true
```

4. Commands (whitelisted chats only): `/status` `/positions` `/pnl` `/features`
   `/pause [SYM]` `/resume [SYM]` `/ask <question>` `/report [24h|7d]`. Dangerous
   ones (`/killswitch`, `/flatten`, `/enable`, `/disable`) require a nonce reply
   `/confirm <nonce>` — that's the safety gate. **Never make port 8000 public**; the
   dashboard is meant to sit behind SSH tunnel / VPN.

---

## 4. Enable the AI analyst (Anthropic or OpenAI)

Read-only assistant on the **AI Analyst** screen + Telegram `/ask` / `/report`.
Pick the cheaper backend if you like — both use the same grounded, read-only prompt.

```bash
# Option A — OpenAI (cheap):
export OPENAI_API_KEY="sk-..."
export AIMOS__ASSISTANT__PROVIDER=openai        # uses gpt-4o-mini by default
export AIMOS__ASSISTANT__ENABLED=true

# Option B — Anthropic:
export ANTHROPIC_API_KEY="sk-ant-..."
export AIMOS__ASSISTANT__ENABLED=true           # provider defaults to anthropic
```

Ask it: "How did the last 7d go?", "Is the ML working?", "Should we paper-trade
more or train more on history?". It's advisory and read-only — it never trades.

---

## 5. Deploy it cheaply (always-on)

A trading loop must be **always-on and restart-on-crash** — so avoid serverless /
free tiers that sleep. Cheapest sensible option is **one small VPS running Docker
Compose** (the app + Postgres on the same box).

**Recommended (cheapest reliable):** a small VPS — e.g. Hetzner Cloud CX22
(~€4–5/mo), or a $5–6/mo droplet on DigitalOcean / Vultr / Linode. 1 vCPU / 2 GB is
plenty for paper + one asset universe.

**Also fine:** Fly.io or Railway with a **persistent volume** (needed for `state/`).
Avoid anything that sleeps the process or wipes disk between deploys.

On the box:

```bash
git clone <repo> && cd aimos
cp .env.example .env          # set TELEGRAM_*, POSTGRES_PASSWORD, keys as needed
docker compose up -d          # aimos (serve) + postgres(TimescaleDB) + watchdog
```

- `docker-compose.yml` binds the app to `127.0.0.1:8000` (not public) and mounts
  `./state` and `./data` as volumes so the journal + candles survive restarts.
- The **watchdog** service restarts the app on a missed heartbeat.
- Reach the dashboard via `ssh -L 8000:127.0.0.1:8000 user@host` then open
  `localhost:8000` — keeps it private.
- **Backups:** `state/aimos.sqlite` is the system of record — back it up (a nightly
  `cp`/`rsync` off-box is enough). Postgres is optional analytics.

### SaaS-enabled deployment

Enable user registration/multi-tenancy with the same Compose stack. The
auth/tenant tables live in the existing Postgres container; no extra service is
needed.

```bash
cp .env.example .env
# enable SaaS and run the one-time migration
docker compose run --rm aimos python -m scripts.migrate_to_saas \
  --admin-email admin@example.com --admin-password 'CHANGEME'
docker compose up -d
```

Then set in `.env`:

```
AIMOS__FEATURES__SAAS_ENABLED=true
AIMOS__SAAS__JWT_SECRET=<32-byte-secret-or-generate-on-first-start>
AIMOS__SAAS__SMTP__HOST=smtp.example.com
AIMOS__SAAS__SMTP__PORT=587
AIMOS__SAAS__SMTP__USERNAME=...
AIMOS__SAAS__SMTP__PASSWORD=...
AIMOS__SAAS__SMTP__FROM=AIMOS <noreply@example.com>
# optional: Google / Apple OAuth credentials
# AIMOS__SAAS__OAUTH__GOOGLE__CLIENT_ID=...
# AIMOS__SAAS__OAUTH__APPLE__CLIENT_ID=...
```

The migration creates a default tenant (`local`) and copies the existing journal
into `state/journals/local.sqlite`. Each new organization gets its own journal
and runtime state in the tenant DB.

Cost floor: a paper deployment runs comfortably for **~$5/month**.

---

## 6. Validate against a real exchange (testnet — free)

Before any real money, prove the live *plumbing* works against Binance's testnet
(real API, fake funds). Full steps in **`specs/TESTNET.md`**; short version:

```bash
# get free testnet keys at https://testnet.binance.vision/ (GitHub login)
export AIMOS_KEY_BINANCE="..." AIMOS_SECRET_BINANCE="..."
# arm a tiny mandate in config/mandate.yaml (enabled: true, small caps)
python -m scripts.validate_integration --exchange binance     # testnet by default
```

A PASS (authenticate → balance → withdrawals-disabled → place → cancel → reconcile)
marks the go-live *testnet* gate. This is integration proof, **not** a profit proof.

---

## 7. Train + enable the ML (optional, disciplined)

Train on older data via paper replay, then enable only if it clears the gate.
Details in `specs/OPERATIONS.md`; short version:

```bash
export AIMOS__LEARNING__HISTORY__ENABLED=true
python -m scripts.train_from_history --csv 'data/BTCUSDT-1h-*.csv' --symbol BTC/USDT
# it prints the walk-forward AUC vs the gate and, only if it passes, the exact:
#   AIMOS__INTELLIGENCE__ML_MODEL_PATH=state/ml_model.json
#   AIMOS__INTELLIGENCE__FUSION_WEIGHTS__ML=0.15   # start small; watch in shadow
```

ML stays in **shadow (weight 0)** until you deliberately raise the weight — and only
after it clears AUC + a shadow window. It refines an edge; it doesn't create one.

---

## 8. Go live — when, and how

### When to go live (all of these, not any of them)

- [ ] **Months of paper** with a **positive, stable** edge — not one lucky week.
      Enough journaled decisions to be statistically meaningful, across regimes.
- [ ] Per-strategy performance makes sense (winners carry their weight; you've
      disabled the persistent losers). Ask the analyst: "which strategy is working?"
- [ ] **Testnet validation PASSES** (§6) — the live path is proven wired.
- [ ] Risk settings you're comfortable losing on: tiny `base_risk_pct`, low
      `max_positions`, a real `daily_stop_pct`.
- [ ] Funded exchange keys with **withdrawals DISABLED** (§23.4) — the boot guard
      refuses keys that can withdraw.
- [ ] You can afford to lose the pilot capital entirely. Start with the minimum.

If any box is unchecked, **keep paper-trading**. There is no penalty for waiting and
a large one for going early.

### How to go live (fail-closed ladder)

Live is gated by three independent locks — you clear them deliberately:

1. **Go-live ladder** (§23.8) — sign off each gate on the **Go-Live** screen (or
   `/api/control/golive`). The boot guard refuses `mode: live` until every gate is
   marked. Testnet gate is marked automatically by §6.
2. **Mandate** (`config/mandate.yaml`) — set a small, explicit ceiling
   (`enabled: true`, tiny `max_total_notional_usdt`, `max_positions: 1`).
3. **Funded, withdrawal-disabled keys** + `mode: live`.

```bash
# only after the ladder is complete + mandate armed + safe keys set:
export AIMOS_KEY_BINANCE=... AIMOS_SECRET_BINANCE=...
# mode:live in config (or AIMOS__MODE=live) — boot guard verifies the ladder first
python -m aimos.runtime.serve
```

Then: start with the **smallest possible size**, watch it live for a while (fills,
slippage vs. paper), and scale up only if live matches paper expectations. The first
live phase is a **pilot to measure the real gap**, not "turn it on and walk away."

### Emergency stop

`/killswitch` on Telegram (nonce-confirmed) or the **Controls** screen halts new
entries immediately. `/pause SYM` pauses one symbol.

---

## Quick reference — env vars

| Variable | Purpose |
|---|---|
| `AIMOS__FEATURES__LIVE_DATA=true` | live public candles (paper; no keys) |
| `AIMOS__MONITOR__ENABLED=true` | run the feature self-test monitor |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_IDS` | Telegram bot + whitelist |
| `AIMOS__FEATURES__TELEGRAM_ENABLED=true` | turn Telegram on |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | AI analyst backend |
| `AIMOS__ASSISTANT__ENABLED=true`, `AIMOS__ASSISTANT__PROVIDER` | enable analyst, pick backend |
| `AIMOS_KEY_<VENUE>` / `AIMOS_SECRET_<VENUE>` | exchange keys (testnet/live) |
| `AIMOS_TIMESCALE_DSN` | optional Postgres/TimescaleDB time-series |
| `AIMOS__MODE=live` | live mode (gated by the ladder + mandate + guard) |

Config lives in `config/*.yaml`; any key is overridable via `AIMOS__SECTION__KEY`.
