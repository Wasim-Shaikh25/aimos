# QUICKSTART — running AIMOS in paper mode

Paper trading needs **no exchange API keys**. It reads *public* market data and
fills against the simulated `PaperBroker`. The only optional secret is a Telegram
bot token (for receiving alerts) and, if you enable it, an Anthropic key for the
LLM news sensor.

## 0. One command — full stack (backend + frontend), install → build → serve
```bash
./run.sh            # offline synthetic data (no keys, no network)
./run.sh --live     # live PUBLIC candles (needs internet; still no API keys)
```
This creates the venv, installs the backend, builds the React dashboard, and
serves **both the API and the dashboard on one port**. Open
**http://localhost:8000** — the dashboard renders live paper-trading state from
the background loop; the API is under `/api`. (Set `TELEGRAM_BOT_TOKEN` in `.env`
first if you want alerts.) Everything below is the manual, piece-by-piece path.

## 1. Run it right now — fully offline, zero keys, zero network
```bash
pip install -e .                 # base runtime (contracts + pipeline)
python -m aimos.runtime.paper_trader --offline --ticks 3
```
This drives synthetic candles through the full pipeline (observation →
intelligence → execution → journal) and prints per-tick regime / p_up / action.
Deterministic and self-contained — good for verifying the wiring.

## 2. Live public data (still no API keys)
```bash
pip install -e '.[data]'         # adds ccxt for public candles
AIMOS__FEATURES__LIVE_DATA=true python -m aimos.runtime.paper_trader --ticks 5
```

## 3. Add Telegram messages (the only secret paper mode uses)
```bash
cp .env.example .env             # then edit:
#   AIMOS__FEATURES__TELEGRAM_ENABLED=true
#   TELEGRAM_BOT_TOKEN=123:ABC   (from @BotFather)
#   TELEGRAM_ALLOWED_IDS=111111  (your numeric chat id)
set -a; source .env; set +a
python -m aimos.runtime.paper_trader --ticks 5
```
Outbound alerts go through the Telegram Bot API over plain HTTPS (no extra
library). With no token it runs in **dry-run** mode and logs the messages instead,
so you can see exactly what would be sent.

## Feature toggles (config/default.yaml `features:` — override with `AIMOS__…` env)
| Flag | Default | Meaning |
|---|---|---|
| `mode` | `paper` | `paper` \| `live` (live requires the §23.8 go-live ladder) |
| `features.telegram_enabled` | `false` | send Telegram alerts (needs `TELEGRAM_BOT_TOKEN`) |
| `features.live_data` | `true` | `true` = live public candles (no keys); `false` = offline synthetic |
| `features.llm_news_sensor` | `false` | §19 LLM sensor (needs `ANTHROPIC_API_KEY`) |
| `features.scalp_enabled` | `false` | §17 minute-scale scalping |
| `features.cross_exchange_enabled` | `false` | §5.11/§7.2 P8 cross-exchange arb (also enable `plugins/cross_exchange_arb.yaml`) |
| `paper.symbols` | `[BTC/USDT, ETH/USDT]` | what to paper-trade |
| `paper.data_exchange` | `binance` | public data venue (no keys) |
| `paper.cross_venues` | `[binance, kraken]` | venues sampled for cross-exchange top-of-book |
| `paper.max_ticks` | `0` | `0` = run forever; `>0` = bounded run |

Any config key is env-overridable: `AIMOS__SECTION__KEY=value` (double-underscore
= nesting). Example: `AIMOS__EXECUTION__BASE_RISK_PCT=0.25`.

## Environment files (local vs prod)
- `.env.example` → copy to **`.env`** for local/dev (git-ignored).
- `.env.prod.example` → copy to **`.env.prod`** for production (git-ignored).
```bash
docker compose up -d                        # uses .env
docker compose --env-file .env.prod up -d   # uses .env.prod
```
Real `.env*` files are git-ignored; only the `*.example` templates are committed.
**Exchange keys are never needed for paper mode** and are commented out in the
templates; they only apply to live mode after the §23.8 gates (and must have
withdrawals disabled, §23.4).

## Docker (all services)
```bash
cp .env.example .env
docker compose up -d      # trading runtime + dashboard (:8000) + telegram + postgres + watchdog
```

## Can I run the whole thing end-to-end with just a Telegram key?
**Yes** — that is exactly what `paper_trader.py` does: public data (no exchange
keys) → the tested pipeline → PaperBroker → Telegram alerts. The dashboard
(`uvicorn aimos.api.server:app`) and the Node frontend build (`dashboard/`) are
separate optional surfaces. What still needs real credentials is only **live
trading** (Phase 6 go-live ladder), never paper.
