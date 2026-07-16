# ACTIVATION GUIDE — what starts dormant, why, and how to turn it on

Nothing in AIMOS is a broken stub. Several components ship **intentionally
dormant** because the build contract (`AIMOS_Implementation_Plan.md`) *requires*
them to stay off until a specific gate is met — this is the safety design, not
missing work. This file is the single place that answers, for every dormant
piece: **what it is, why it's off, the trigger to turn it on, and exactly how.**

Legend:
- **Flag** = the config key / env var that controls it.
- **Trigger** = the condition the spec requires before you flip it.

---

## 1. Live trading (the big one) — `mode: paper → live`
- **Why off:** live order execution is gated behind the §23.8 go-live ladder.
  Trading real money before validation is the one thing the whole design forbids.
- **Trigger (§23.8, in order, each journaled):**
  1. 12-month backtest passes §20.2 validation (permutation p<0.05, Sharpe CI>0)
  2. ≥ 4 weeks paper trading; paper metrics within CI of backtest
  3. 1 week exchange testnet (order lifecycle, partial fills, cancels, reconcile)
  4. Security checklist §23.4 signed off + restore drill done
  5. 10% canary live, 2 weeks
  6. Scale in 25% steps, one per 2 green weeks
- **How:** set `mandate.yaml` `enabled: true` with real limits, provide
  **withdrawal-disabled, IP-whitelisted** API keys (`BINANCE_API_KEY/SECRET` in
  `.env.prod`), then `AIMOS__MODE=live`. `LiveBroker` refuses to start if the key
  has withdrawal permission (§23.4) or the mandate isn't satisfied (fail-closed).
- **Code:** `aimos/execution/broker/live.py` — real ccxt `create_order` path,
  idempotent client ids, `reconcile_on_start`. Tested to the ccxt boundary; only
  real keys + testnet make it actually place orders.

## 2. ML engine fusion weight — `intelligence.fusion_weights.ml: 0.0 → 0.10+`
- **Why 0:** the ML model must not influence trades until it's proven. It runs in
  **shadow** (predicts, is logged, weight 0) so you compare its calls to reality
  first (§6.3, §8.3). The engine is NOT a stub — it trains and predicts (pure
  numpy logistic regression, `learning/model.py`); it's simply not trusted yet.
- **Trigger (§8.3 promotion ladder):** journal ≥ 2,000 labeled samples →
  walk-forward val AUC > 0.55 + Brier improves → 2 weeks shadow with calibration
  holding → **human** raises the weight.
- **How:**
  1. `python -m aimos.learning.train` (fits on journal features/labels, walk-
     forward validated, saves a model artifact; see `learning/train.train_model`).
  2. Point the engine at it: `intelligence.ml_model_path: state/model.json`.
  3. After the shadow window, set `intelligence.fusion_weights.ml: 0.10` (up to
     0.40 as it proves out) and restart. `learning/train.shadow_weight()` keeps
     it 0 until this config change — no auto-deployment.

## 3. LLM news sensor — `features.llm_news_sensor: false → true`
- **Why off:** it needs an `ANTHROPIC_API_KEY` and adds a network dependency;
  ships off until Phase 5 (§19).
- **Trigger:** you want richer news evidence than the keyword lexicon and accept
  the API cost. Injection defenses + cache-or-die replay are always on.
- **How:** `AIMOS__FEATURES__LLM_NEWS_SENSOR=true` + `ANTHROPIC_API_KEY=...`.
  Wire the classifier callable into `observation/sentiment_llm.LLMNewsSensor`
  (the parse/clamp/cache/allowlist logic is real and tested); a live API outage
  auto-falls back to the lexicon. Reliability recalibrates monthly (§8.4).

## 4. Telegram alerts + commands — `features.telegram_enabled: false → true`
- **Why off:** needs a bot token; optional.
- **How:** `AIMOS__FEATURES__TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_ALLOWED_IDS`. Outbound alerts (`telegram/sink.py`) go over plain
  HTTPS; inbound commands (`telegram/bot.py`) poll and route through the
  whitelist + nonce-confirm security. With no token it dry-runs (logs). **Fully
  functional today** — this is the "just a Telegram key" path.

## 5. Scalping fast loop — `scalp.enabled: false → true` (`features.scalp_enabled`)
- **Why off:** minute-scale trading only works with maker fills on T1-liquid
  assets and needs websocket streams; Phase 6, after 5m paper results exist
  (§17.1). The EV formula correctly rejects most 1m trades — that's the system
  working, not a bug.
- **Trigger:** live is stable AND scalp backtests on **recorded order-book data**
  (not candle-proxy — those are stamped `LOW_FIDELITY`, §17.5) pass the gate.
- **How:** `scalp.enabled: true`; the context gate (`runtime/fast_loop.py`) only
  lets scalps run inside a trending/ranging slow-loop context, T1, off the
  funding window, with a healthy stream.

## 6. On-chain engine — inert → active (needs a data provider)
- **Why inert:** §5.9 ships it as a registered Phase-1 stub; it activates in
  Phase 3 with on-chain APIs. The engine is real (`observation/onchain_engine.py`
  computes active-address / stablecoin-inflow z-scores) — it just has no feed
  wired by default.
- **How:** construct it with an `OnchainProvider` (`data/onchain.py`:
  `FreeApiOnchainProvider` for live free endpoints, `StaticOnchainProvider` for
  fixtures) and set `engine.provider`. With a provider it emits real evidence.

## 7. Cross-exchange lead-lag / venue-divergence — real, data-gated
- **Why quiet:** these need **per-venue time series / rel-vols**, which the frozen
  `MarketContext` (aggregates only) doesn't carry — they arrive with the cryptofeed
  stream layer (§5.11 rules 2-3, a Phase-2 feature). The algorithms are real and
  tested (`compute_lead_lag`, `venue_divergence`).
- **How:** give `CrossExchangeEngine(..., venue_series_provider=, venue_relvol_provider=)`
  and it emits `lead_lag` / `venue_divergence_volume`.

## 7b. Cross-exchange arbitrage (P8) — built, disabled by default
- **What:** `price_dislocation` (USD-converted, depeg-safe §16.1 B-3) is surfaced
  into `MarketUnderstanding.key_levels["dislocation"]`; the **`CrossExchangeArb`**
  plugin (`plugins/cross_exchange_arb.py`) turns a spread that clears
  round-trip costs + `extra_margin_bps` into a simultaneous **buy(cheap)/sell(rich)**
  candidate (`meta.cross_venue`, `buy_venue`, `sell_venue`). Path is real and
  tested end-to-end (`tests/test_cross_exchange_arb.py`).
- **Why off:** true cross-venue execution needs **dual-venue balances** on both
  legs (§7.2 P8, Phase 3) and a populated `venue_snapshot`. Enabling it in paper
  mode exercises the full observation→intelligence→plugin→evaluator path against
  either synthetic per-venue books (offline) or live PUBLIC top-of-book (no keys).
- **How:** set `features.cross_exchange_enabled: true` **and**
  `plugins/cross_exchange_arb.yaml enabled: true`. The paper/serve loop then builds
  `venue_snapshot` across `paper.cross_venues` (live books when `live_data`, else a
  deterministic synthetic dislocation). Live cross-venue *fills* still require the
  §23.8 go-live ladder plus balances on each named venue.

## 8. Ignition trading — detector on, plugin gated
- **Why gated:** the MomentumIgnition plugin trades violent repricings from a
  caged sub-book (§23.11B); it only fires inside a 15-min entry window on an
  *organic* (non-PnD) ignition. `IgnitionFade` is deliberately **not built** — the
  spec requires ≥ 3 months of labeled ignition outcomes first (§23.11 B-last).
- **How:** thresholds in `config/ignition.yaml`; wire the all-market miniTicker
  stream to the detector and the ignition context into `key_levels['ignition']`.

## 9. Market making P9 — `plugins/market_making.yaml enabled: false → true`
- **Why off:** MM under ~$5k allocated capital gets eaten by fees, so the plugin
  refuses below `min_capital_usd` (§21.2); Phase 6, needs live inventory.
- **How:** `enabled: true`, ≥ $5k equity, RANGING regime, and feed the book
  snapshot into `key_levels['mm']`. Withdraws all quotes on manipulation.

## 10. Agents A1–A3 — Phase 6, feature-flagged off
- **Why off:** the agents (Research Analyst, Risk Sentinel, Ops) are LLM-adjacent
  and human-gated (§18.3). A1 only writes **staging** proposals, never live config;
  A2 can only *notify*; A3 has a fixed action allowlist. All three are built and
  tested (`aimos/agents/`).
- **How:** enable in config + run their schedules; approvals flow through the
  CONFIRM-gated `/proposals` endpoint (writes staging, not live config).

## 11. Factor engine (Module 14) — needs a selection run
- **Why quiet:** `config/factors_active.yaml` ships empty; the engine emits
  nothing until alphas are selected (§20.1).
- **How:** `python -m aimos.learning.factor_select` builds the panel, runs the IC
  benchmark, and writes surviving alphas to `factors_active.yaml`. Then the
  `FactorEngine` emits `factor_<id>` evidence.

## 12. Vendored code — frozen by design
- **Why "reference" not upstream:** `vendor/*` holds working clean-room
  implementations. Copying the actual upstream repos at pinned SHAs is a
  deliberate, human-approved event (§22.3), not automatic.
- **How:** follow the `vendor/VENDOR.md` procedure (clone at SHA → copy manifest
  paths → attribution headers → record SHA), then run the vendor smoke suites.

## 13. Recorded 12-month dataset (P1-T6)
- **Why absent:** it's data, not code, and needs network.
- **How:** `pip install -e '.[data]'`, then per symbol/tf
  `python -m aimos.data.candles --symbol BTC/USDT --tf 1h --depth 8760`, verify
  with `python scripts/dataset_integrity.py data/`. Required for the §23.8
  validated backtest.

## 14. React dashboard — builds today
- **Status:** **working** — `cd dashboard && npm install && npm run build`
  compiles (Vite, 9 real screens). `npm run dev` proxies `/api` to the FastAPI
  backend. Not dormant; just needs a Node toolchain to build the frontend bundle.

---

## Quick reference — the flags
| Flag / key | Default | Turns on |
|---|---|---|
| `mode` | `paper` | live trading (after §23.8 ladder) |
| `mandate.enabled` | `false` | the live-trading fail-closed contract |
| `intelligence.fusion_weights.ml` | `0.0` | ML influence (after shadow, §8.3) |
| `features.llm_news_sensor` | `false` | LLM news sensor (needs Anthropic key) |
| `features.telegram_enabled` | `false` | Telegram alerts + commands |
| `features.scalp_enabled` / `scalp.enabled` | `false` | minute-scale scalping |
| `plugins/market_making.yaml enabled` | `false` | market-making P9 |
| `features.cross_exchange_enabled` + `plugins/cross_exchange_arb.yaml enabled` | `false` | cross-exchange arbitrage P8 (needs dual-venue balances for live fills) |
| `features.live_data` | `true` | live public candles vs offline synthetic |

Everything else (all 13 observation engines, rule/bayes/fusion, execution,
journal, backtester, paper loop, watchdog, risk analytics) is **active by
default** and covered by the test suite.
