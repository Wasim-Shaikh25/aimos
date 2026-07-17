# AIMOS — Multi-Venue Trading & Operator Dashboard Requirements

Status: **DRAFT for review** · Owner: you · Author: build agent · Date: 2026-07-17

This is the spec we build against next. It extends AIMOS from *single-venue
analysis + keyless monitoring* to: (1) full observation/decision loops across all
platforms, (2) a real multi-venue **trading mechanism that is implemented but
gated off**, and (3) an operator dashboard where every panel is a *working*
surface — prices per platform, observation values, a decision mind-map, balances,
trade history, and performance.

## 0. Guiding principles (the anti-scaffold contract)

1. **No placeholders.** A feature is "done" only when it meets the Definition of
   Done in §8 — a real backend endpoint, a UI that renders live data, an
   automated test, *and* it's demonstrable offline (simulated) **and** works with
   real venues/keys when provided.
2. **Keyless by default.** All *analysis* (candles, tickers, order books) uses
   PUBLIC data and never needs API keys. Keys are only ever used for
   **account access** (balances, positions, order placement).
3. **Safety first.** Live execution is OFF by default, behind feature flags + the
   §23.8 go-live ladder + the mandate gate (withdrawals disabled, §23.4).
4. **Everything visible.** If the backend computes it, the dashboard shows it.

---

## 1. Scope

**In scope**
- Multi-venue observation + decision loops for all analyzed coins.
- Multi-venue trading mechanism (router + per-venue brokers + two-leg arb
  execution), fully implemented, disabled by default, with a simulated broker so
  it runs and is visible now.
- Key/secret handling model + a **startup connectivity self-check**.
- Dashboard: multi-platform price matrix, observation values, decision mind-map,
  balances, trade history, performance.

**Out of scope (for this phase)**
- Real fund movements / withdrawals (permanently out — withdrawals stay disabled).
- HFT / sub-second co-located execution (loop-cadence is fine for now).
- New trading strategies beyond what already exists.

---

## 2. Key & secret handling model  *(answers your two questions)*

**2.1 Keys are only for account access — analysis stays keyless.**
- Public market data → no key, ever. The observe→understand→execute analysis path
  must never require or touch a key.
- Account-scoped calls (fetch balance, fetch my positions, place/cancel order)
  → require that venue's key, and are only invoked when a feature that needs them
  is enabled (live trading, balance UI, preflight check).

**2.2 Lazy, need-based key use** *(your point: "passed during analysing data to
fetch data only when we really need for my account access")* — **Yes, exactly.**
- The system builds an *authenticated* client for a venue **only** when an
  account-access feature is turned on. Until then no key is read and no
  authenticated client exists. Same data pipeline, keys attached only on the
  account-access branch.

**2.3 Where secrets come from** *(your point: "place my secret somewhere and
during startup you fetch and use it")* — supported via a precedence chain:
1. `AIMOS_SECRETS_FILE=/path/to/secrets.yaml` (a file you place anywhere; mounted
   read-only in Docker), then
2. individual env vars (`AIMOS_KEY_BINANCE`, `AIMOS_SECRET_BINANCE`, …), then
3. `.env`.
- Secrets are never logged, never journaled, never sent to the UI (the UI only
  ever sees a boolean "connected: true/false" and the venue name).

**2.4 Startup connectivity self-check (automation)** *(your point: "so you can
check with automation that everything is working")* — **Yes.** On startup, for
each venue with a configured key, run a **read-only preflight**:
- authenticate, `fetch_balance` (read-only), confirm the key works,
- assert the key has **no withdrawal permission** (fail closed if it does, §23.4),
- report per-venue `{connected, can_trade, withdrawal_disabled, balances_ok}` to
  the dashboard (a "Connections" panel) and optionally Telegram.
- **No orders are placed.** This is the automated "is everything wired?" check.

---

## 3. Multi-venue observation & decision loops

**3.1 What runs per platform.** For every analyzed coin:
- **Deep TA** (candles/indicators/structure) runs on the coin's **primary venue**
  (fetching full history from every venue each tick is wasteful and the
  candles are ~identical). *Recommended default.*
- **Per-venue overlay**: live top-of-book (mid/bid/ask/spread) is fetched from
  **every venue the coin trades on**, feeding the cross-exchange engine
  (dislocation, lead-lag, venue-divergence).
- Result: one `MarketUnderstanding` per coin **plus** per-venue price/spread data
  and cross-venue evidence.

**3.2 Acceptance.** For each top-N coin the dashboard can show: its per-venue
prices, every engine's observation values, and the resulting decision + reason.

> Open decision (see §9): deep TA **primary-only + overlay** (recommended) vs.
> **independent full analysis per venue** (heavier, rarely different signal).

---

## 4. Multi-venue trading mechanism (implemented, gated OFF)

**4.1 Components to build**
- `VenueBroker` interface; `PaperVenueBroker` (simulated fills per venue) and
  `LiveVenueBroker` (ccxt, mandate-gated, idempotent client-order-id, withdrawal
  check) — one instance per venue.
- `MultiVenueRouter`: given a cross-venue `TradePlan` (`buy_venue`/`sell_venue`),
  place **both legs**; handle partial / one-leg fills; track exposure per venue.
- `BalanceManager`: per-venue balances (real via read-only key, or simulated);
  enforces "can't sell what you don't hold on that venue"; per-venue capacity.
- `PaperMultiVenueBroker`: simulates the whole two-leg flow so it runs and is
  visible **now**, with no keys.

**4.2 Gating.** Everything OFF by default: `mode: paper`,
`execution.multi_venue_enabled: false`, live venues empty. Turning on live
requires the §23.8 ladder + funded balances + per-venue keys.

**4.3 Acceptance.**
- With the simulated broker, an arb decision produces **two paired legs**,
  journaled, and shown in Trade History as a linked cross-venue trade.
- The live path exists and is unit-tested against a **mock ccxt exchange**
  (submit, partial fill, reconcile) but is gated off.

**4.4 You will need crypto/inventory on each venue** for live arb (documented as a
precondition — buy-cheap needs quote on venue A, sell-rich needs base on venue B).
The BalanceManager surfaces whether inventory is sufficient before proposing.

---

## 5. Dashboard requirements (each item = working + DoD)

**5.1 Multi-platform price matrix** — rows = coins, columns = venues; each cell
shows live **mid / bid-ask spread**, plus a **dislocation** column (max pairwise
bps) and the cheap→rich venues. Live-polled. *DoD: `/api/prices/matrix` returns
per-venue tops; screen renders the grid; test asserts multi-venue cells.*

**5.2 Observation values** — per coin, every engine's evidence (name, direction,
value, strength, reliability). *(Engines screen exists; extend to flag which
signals are cross-venue.)*

**5.3 Decision mind-map** — a visual node graph of one decision:
evidence → engines (rule/bayes/ml) → fusion → regime/behavior → strategies
*considered* (with pass/veto reason) → **chosen** (or NO_TRADE), each node showing
its number and "why". *DoD: `/api/decision/{id}/graph` returns nodes+edges; a
mind-map screen renders it; test asserts the chosen path is present.*

**5.4 Balance check UI** — per-venue balances (free/used/total per asset),
connection status from the §2.4 preflight. Shows "no key — connect to view" when
absent (never blocks the rest of the app). *DoD: `/api/balances` (simulated or
real); screen renders; test with a mock balance provider.*

**5.5 Trade history UI** — every position/fill: open/close time, venue(s), side,
size, entry/exit, PnL, strategy; cross-venue legs shown paired. *DoD:
`/api/trades` from the journal; screen renders; test asserts a placed trade
appears.*

**5.6 Performance UI (make it real)** — equity curve, realized/unrealized PnL,
win rate, avg R, max drawdown, breakdown **per strategy** and **per venue**.
Replace today's flat placeholder with real computed metrics. *DoD: `/api/performance`
computes from the journal; screen renders tiles + curve; test vs. a fixture.*

---

## 6. Non-functional / safety
- Decision-path stays free of hardcoded tunables (existing magic-number lint).
- Live execution behind §23.8 ladder + `mandate.yaml`; withdrawals disabled.
- Secrets never logged/journaled/sent to UI.
- Loop never dies on a single venue/coin error (per-venue isolation).
- All new config keys documented + env-overridable.

---

## 7. Configuration additions (proposed)
```yaml
execution:
  multi_venue_enabled: false        # master switch for cross-venue execution
  venues: [binance, kraken, coinbase]
  per_venue_max_equity_pct: 40      # capacity cap per venue
account:
  preflight_on_start: true          # run the read-only connectivity self-check
  require_withdrawal_disabled: true # fail closed if a key can withdraw
secrets:
  file: ""                          # AIMOS_SECRETS_FILE path (optional)
```

---

## 8. Definition of Done (global — the anti-scaffold gate)
A feature ships only when **all** are true:
1. Backend endpoint returns **real** data (from journal/live/simulated), not a stub.
2. UI screen renders it with **live polling** and sensible empty/errored states.
3. An **automated test** covers it (endpoint + core logic).
4. It's **demonstrable offline** (simulated data / mock venue) with no keys.
5. It **works with real keys/venues** when provided (verified by the §2.4 preflight
   for account features).
6. Docs updated (QUICKSTART / ACTIVATION_GUIDE / this file's checklist).

---

## 9. Open decisions to confirm before building
1. **Per-venue analysis depth:** primary-venue deep TA + per-venue price overlay
   (recommended) — or full independent analysis per venue?
2. **Initial venues:** binance + kraken + coinbase — confirm the set.
3. **Secret storage:** a mounted `secrets.yaml` file (recommended) vs. individual
   env vars vs. a vault?
4. **Build order:** simulated multi-venue first (visible now, no keys), then live
   path gated (recommended) — or live path first?
5. **Arb capital model:** fixed per-venue inventory, or dynamic rebalance? (affects
   the BalanceManager scope)

---

## 10. Proposed phased delivery
- **Phase A — Multi-venue observation + price matrix + observation values**
  (keyless, demonstrable immediately).
- **Phase B — Simulated multi-venue trading** (`PaperMultiVenueBroker`) +
  **Trade History** + **Balances (simulated)** + **real Performance**.
- **Phase C — Decision mind-map.**
- **Phase D — Live multi-venue execution (implemented, gated)** + key preflight
  self-check + real Balance UI.

Each phase ends green (tests + lints) and with screenshots of the working UI.

---

## 11. Traceability — your requests → where they're covered
| Your request | Section |
|---|---|
| Implement trading mechanism, disable-able | §4 |
| Run observation + decision loops for all platforms | §3 |
| Dashboard: crypto values per platform in columns | §5.1 |
| Values of different observations + what decision | §5.2, §5.3 |
| Trading shown as a mind map | §5.3 |
| Balance check UI | §5.4 |
| Trade history UI | §5.5 |
| Performance UI working | §5.6 |
| No API key for current (public) analysis | §2.1 |
| Key passed only when fetching my account data | §2.2 |
| Place secret somewhere; fetch at startup; auto-verify | §2.3, §2.4 |
| Everything working, not scaffold | §0, §8 |
