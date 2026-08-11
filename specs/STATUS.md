# STATUS — what's built, what's dormant, what's next

**Objective:** the single source of truth for implementation state. Read this +
`CHANGELOG.md` before starting work. (Consolidates the former BUILD_TASKS and the
multi-venue/dashboard requirements.)

Legend: ✅ done & tested · 🟡 built but gated/dormant (real code, needs a
prerequisite) · ⏭️ not built yet.

---

## Core build (Phases 0–6) — ✅ done

| Phase | What | State |
|---|---|---|
| 0 | Contracts (pydantic v2), config tree, clock, bus, import-linter | ✅ |
| 1 | Data infra: candles, orderbook, funding, whale, sentiment, rate-limit | ✅ |
| 1.5 | Universe manager: discovery, filters, tiers, registry, intersection, depeg | ✅ |
| 2 | Observation: all 13 engines | ✅ |
| 3 | Intelligence: rule + bayes + fusion + scores + confidence + explain | ✅ |
| 4 | Execution: plugins, evaluator, sizer, risk manager, journal (hash chain), backtester | ✅ |
| 5 | Runtime, API, React dashboard, Telegram, ignition, risk analytics | ✅ |
| 6 | Learning (shadow), agents, LLM sensor, live broker, go-live gates | ✅ |
| SaaS P1 | Single-admin auth seeded from config/env, email OTP 2FA, JWT, tenant orgs (multi-user UX removed) | ✅ |
| SaaS P2/P3 (partial) | Runtime state persistence, per-tenant config/journal/state store, broker/sim resume, streaming scaffold + feed into paper loop, ML registry, dashboard equity + candlestick charts, evidence tables, decision anatomy, org settings, auth screens, org scoping, migration, Dockerfile, vendor manifest + vendoring script, live multi-venue executor wiring (fail-closed), tests | ✅ |

The §25.9 golden worked example reproduces exactly (fusion 0.766/0.428; execution
NO_TRADE, EV −0.018). **535 passed, 1 xfailed**; magic-number + naive-datetime lints
clean; import-linter 6/6.

> ✅ **Production readiness: STOP — CONDITIONAL GO.** See **`PRODUCTION_READINESS_AUDIT.md`**.
> **All Critical/High/Medium audit blockers are fixed** — the 2 Criticals (C1
> traversal, C2 auth-lockout) verified live, and H1–H5 + M8 + L5 fixed with tests
> (466 → 516). The H3 `email_login_codes.attempts` schema change is now an Alembic
> migration (REQ-9), the backup scheduler runs hourly by default (REQ-12), the
> network-exposure model is documented as loopback-only/proxy-or-SaaS (REQ-10),
> and key material defaults to `~/.aimos/secrets` with a dedicated Docker secrets
> volume (REQ-14). The dormant on-chain engine now has a Coin Metrics Community
> API provider (REQ-16), and the dashboard accessibility pass is complete
> (REQ-15). The independent verification pass is complete and the two go-live
> blockers it found are fixed: killswitch can now be reset via `POST
> /api/control/unhalt` and the dashboard Controls screen, and `/api/v2/status` now
> surfaces runtime feature flags plus `halted` state.
>
> **REQ-13 (API/loop process split) is implemented.** `AIMOS_PROCESS=combined/api/loop`
> selects whether `serve.py` runs both the API and loop, only the API with a
> `RuntimeStateStore`/ControlStore rehydration task, or only the loop via
> `python -m aimos.runtime.loop_process`. `OrganizationState` gained `view` and
> `controls` JSON columns with an Alembic migration.

---

## Multi-venue + operator dashboard (Phases A–D) — ✅ done

- **A — Per-venue analysis + price matrix.** The full observe→decide pipeline runs
  on every venue a coin trades on (binance/kraken/coinbase). Dashboard: multi-
  platform price matrix (mid + per-venue decision + dislocation), per-venue Engines.
- **B — Simulated multi-venue trading.** `MultiVenueSim` executes arb as two legs
  (buy cheap / sell rich), inventory-constrained. Trade History, Balances (per
  venue), real Performance (win rate, PnL, per-strategy/venue, drawdown).
- **C — Decision mind-map.** `/mindmap` renders one decision as a node graph:
  engines → fusion → regime → eligible strategies → chosen.
- **D — Live path (gated) + preflight + connections.** `LiveBroker` +
  `MultiVenueLiveRouter` (mandate + withdrawal gated, mock-tested); read-only key
  preflight self-check + Connections panel; secret loading (file + env); real
  balance UI. Scalp enabled (MomentumScalp + proxy micro-engine).

Plus: runtime feature toggles (UI + Telegram), go-live ladder tracker with UI
progress, testnet order probe, hard live-boot guard, TimescaleDB time-series store,
live-integration validator (`scripts/validate_integration.py`, testnet — see
`specs/TESTNET.md`), and a **feature monitor agent** (background self-tester that
probes every feature, publishes a coverage report at `/api/monitor` + the Monitor
screen, and can force the safe keyless flags on to exercise every path). Plus a
**read-only AI analyst** (`/ask`, `/report` on the UI + Telegram — grounded in the
journal + metrics, sensor/explainer only; see `specs/ASSISTANT.md`), and ML
training on historical data via paper replay (`scripts/train_from_history`).

---

## Dashboard screens — ✅ all live-polling

Markets · Prices (multi-venue matrix) · Decision Anatomy · Mind-map · Engines
(per-venue) · Strategies · Models · Universe · Positions & Risk · Trade History ·
Balances · Connections · Controls · Go-Live · Monitor · AI Analyst · Decisions ·
Performance · Config · Agents · Settings.
- Risk analytics (`/api/risk`) live on the **Positions & Risk** stress panel and **Performance** alpha/beta tiles (REQ-1).
- Go-Live ladder enforces sequential gate sign-off (REQ-8).
- Public `/healthz` and `/readyz` probes are live, with `docker-compose.yml` healthcheck wired (REQ-6).

---

## Dormant — 🟡 real code, gated on a prerequisite

| Item | Gate |
|---|---|
| Live trading | go-live ladder + funded, withdrawal-disabled keys |
| Live multi-venue **execution** | ladder + pre-funded inventory per venue (`multi_venue_live`) |
| ML fusion weight (0.0) | shadow calibration checklist (§8.3) — train a model first with `scripts/train_from_history` (off by default), then raise the weight only after it clears the AUC gate + shadow window |
| LLM news sensor | `ANTHROPIC_API_KEY` |
| On-chain engine | an `OnchainProvider` |
| Cross-venue lead-lag / venue-divergence | per-venue price-stream provider |
| Market making (P9) | ≥ $5k live capital |
| IgnitionFade | ≥ 3 months labeled ignition data |
| Agents A1–A3 | enable + human approval flow |

---

## Not built yet — ⏭️ candidates

- **Real-exchange validation** of the live path — the validator harness exists
  (`scripts/validate_integration.py`, mock-tested); the actual testnet *run* needs
  the operator's free testnet keys (`specs/TESTNET.md`).
- **Live multi-venue executor** wired into the serve loop (router exists; routing
  live arb through it end-to-end is the next execution step).
- **Streaming layer** for real 1m scalp + real cross-venue top-of-book + lead-lag.
- **TimescaleDB dashboards / retention** on the time-series it now writes.
- The **12-month recorded dataset** download (P1-T6) and upstream **vendoring** at
  pinned SHAs (P15-T4).

Runtime state (equity/balances/broker/sim/ladder) persists across restarts via
`RuntimeStateStore` (`aimos/runtime/state_store.py`, atomic writes since the M8
fix). A unified operational database option is available: set
`storage.database_url` (or `AIMOS__STORAGE__DATABASE_URL`) and the journal,
runtime state, controls, and model registry all live in PostgreSQL/SQLite; the
file/SQLite paths remain the default fallback for dev/tests.

**Robustness/security/ops backlog:** see **`specs/REQUIREMENTS_BACKLOG.md`** —
19 tracked requirements from the production-readiness audit's residual items and
a competitive review against TradingAgents / OpenBB, prioritized into four tiers.

---

## Hard rules (don't regress)

- Contracts only between layers; import direction enforced by import-linter.
- **No LLM in the decision path** (§15.3) — sensor/explainer only.
- No hardcoded tunables in `observation/`, `intelligence/`, `execution/` (magic-
  number lint); all time via `clock.now()`; SHA-256 hash-chained journal.
- Live trading fail-closed: mandate + ladder + boot guard.
