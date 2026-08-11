# TASKS — tracked backlog with acceptance criteria and test cases

**Purpose:** the single tracked backlog. `specs/STATUS.md` says *what exists*;
this file says *what to do next, in what order, and how you know it's done*.

**Legend:** ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked

**Priority:** **P0** = blocks everything downstream · **P1** = correctness/safety ·
**P2** = quality/coverage · **P3** = new capability

Every task carries: **why**, **files**, **acceptance criteria**, and **test cases**.
A task is not done until its tests are written *and green*.

---

## Dependency graph

```
T-001 (outcomes loop) ─┬─► T-003 (costed backtest) ─┬─► T-010 (fit config)
                       │                            └─► T-020..T-025 (Kronos K1-K5)
                       └─► T-004 (attribution/analyst grounding)

T-002 (arb bugs) ──────► T-003          T-030..T-047 (test coverage) run in parallel
```

**The critical path is T-001 → T-003.** Nothing about profitability, strategy
quality, or the forecaster can be answered until those two land.

---

# P0 — the measurement loop

## T-001 ⬜ Journal trade outcomes (close the loop)

**Priority:** P0 · **Blocks:** T-003, T-004, T-020+ · **Est:** M

### Why

`aimos/journal/journal.py:101` implements `write_outcome()` — fully written,
hash-chained, with a matching `outcomes` table and an `OutcomeRecord` contract at
`aimos/core/schemas.py:197`.

**It is called by zero production code.** The only references anywhere are its own
definition and `tests/test_schemas.py:106`.

Consequence, confirmed against the live DB:

```
decisions   2760
outcomes       0     ← the loop has never closed, once
```

Everything downstream is starved by this one missing call: ML training labels,
per-strategy win rates, the AI analyst's attribution answers, drift detection, and
the Kronos shadow gate (KR-31) all read outcomes that do not exist.

### What already works (do not rebuild)

`PaperBroker._close()` (`aimos/execution/broker/paper.py:206`) already computes
almost the whole record:

| `OutcomeRecord` field | Available at `_close()`? |
|---|---|
| `decision_id` | ✅ `pos.decision_id` |
| `exit_time` | ✅ `now` |
| `exit_price` | ✅ `price` |
| `pnl_quote` | ✅ `pnl` |
| `pnl_r` | ✅ already computed — `pnl / initial_risk_quote` |
| `exit_reason` | ✅ `kind` (`"sl"` / `"tp"`) |
| `max_adverse_r` (MAE) | ❌ **not tracked** |
| `max_favorable_r` (MFE) | ❌ **not tracked** |

So the real work is: **track excursion, then wire one call.**

### Design constraints

- **`Position` is `extra="forbid"` in `schemas.py`** — a hard-rule file (no edits
  without human approval). So MAE/MFE must **not** become Position fields. Track
  them in a broker-side `dict[decision_id, (mae_r, mfe_r)]` instead. This avoids
  the approval gate entirely.
- **The broker must not import the journal.** Decisions are journaled by the
  runtime (`aimos/runtime/pipeline.py:139`), not by the broker. Mirror that: the
  broker *exposes* closed outcomes, the runtime *writes* them.
- **Backtest parity.** `aimos/backtest/engine.py:112` journals decisions too; it
  must journal outcomes by the same path, or backtest and live diverge.

### Implementation

1. In `PaperBroker.step()`, update running MAE/MFE per open position from each
   bar's high/low, in R units against `initial_risk_quote`.
2. In `_close()`, build the `OutcomeRecord` and append to a
   `self.pending_outcomes: list[OutcomeRecord]`.
3. Add `drain_outcomes() -> list[OutcomeRecord]` (returns and clears).
4. In `pipeline.py` and `backtest/engine.py`, drain after each tick and
   `journal.write_outcome(...)` each one.

### Acceptance criteria

- [ ] A paper position that hits SL or TP produces exactly one `outcomes` row.
- [ ] `pnl_r` in the row equals the value appended to `closed_trades_r`.
- [ ] MAE ≤ 0 ≤ MFE for every record; `|MAE|` ≤ the R distance to the stop.
- [ ] The hash chain still verifies after outcome writes (`journal/verify.py`).
- [ ] Backtest and paper produce identical outcome rows for identical bars.
- [ ] Nothing is written for positions still open.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-001.1 | Long hits TP | one row, `exit_reason == "tp"`, `pnl_r > 0` |
| T-001.2 | Long hits SL | one row, `exit_reason == "sl"`, `pnl_r ≈ −1` |
| T-001.3 | Short hits TP | sign handling correct (`pnl_r > 0`) |
| T-001.4 | Position never closes | **zero** outcome rows |
| T-001.5 | MAE/MFE tracked across 5 bars | MAE = worst excursion, MFE = best, both in R |
| T-001.6 | Same bar touches SL and TP | SL wins (worst case, matches `_check_exits`) |
| T-001.7 | Hash chain after 10 mixed writes | `verify_chain()` passes |
| T-001.8 | `drain_outcomes()` twice | second call returns `[]` (no double-journal) |
| T-001.9 | Backtest vs paper, same bars | outcome rows byte-identical |
| T-001.10 | `pnl_r` vs `closed_trades_r` | identical for every closed trade |
| T-001.11 | Zero `initial_risk_quote` | no crash, no divide-by-zero, row skipped or `pnl_r=0` |
| T-001.12 | Journal write fails (disk full) | trade still closes; error logged; no crash (§10.1) |

**New test file:** `tests/test_outcomes_loop.py`

---

## T-002 ⬜ Fix cross-exchange arb phantom spreads

**Priority:** P0 · **Blocks:** T-003 (arb backtest numbers are meaningless until fixed) · **Est:** S

### Why — two independent bugs that both inflate the spread

**Bug A — mid-to-mid instead of ask/bid.**
`aimos/observation/cross_exchange.py:112`:

```python
mids = {v: top.mid for v, top in snap.items()}
result = compute_dislocation(mids)
```

`VenueTop` carries `best_bid` and `best_ask` (`schemas.py:254`) and both are
**thrown away**. But a real arb *buys at the cheap venue's ask* and *sells at the
rich venue's bid*. Mid-to-mid overstates every capture by roughly one full
bid-ask spread — and it does so *before* the plugin subtracts costs, so the
`net_bps > 0` gate in `cross_exchange_arb.py:52` passes on spreads that are
already fictional.

**Bug B — quotes are not contemporaneous, and the timestamp hides it.**
`aimos/data/live_source.py:105` fetches venues in a sequential loop, then stamps
every one with the same `now`:

```python
for venue in venues:
    bid, ask = f.fetch_top_of_book(symbol)   # sequential REST, hundreds of ms apart
    snap[venue] = VenueTop(..., timestamp=now)   # ← same 'now' for all
```

So `VenueTop.timestamp` records when the *loop started*, not when each quote was
observed — it is structurally incapable of detecting staleness. And
`compute_dislocation()` takes `Mapping[str, float]`; timestamps never reach it, so
**no staleness gate exists anywhere on this path.**

### Evidence this is not theoretical

The journal's 86 arb trades logged spreads of **29.7 / 36.0 / 38.9 / 52.9 / 59.0
bps** on majors. Real Binance↔Coinbase↔Kraken spreads on BTC are 1–5 bps and close
in milliseconds. Those numbers match the signature of
`synthetic_venue_snapshot(dislocation_bps=30.0)` (`live_source.py:80`) — test data
doing its job. But the same code path in live mode has no guard that would catch a
real phantom.

### Implementation

1. Pass `VenueTop` objects (not floats) into `compute_dislocation`; compute the
   executable spread as `bid[rich] − ask[cheap]`, not `mid − mid`.
2. Stamp each `VenueTop` with its **own** fetch time in `live_venue_snapshot`.
3. Add a config'd `max_quote_age_seconds` and `max_venue_skew_seconds`; drop stale
   venues and return `None` when fewer than 2 fresh venues remain.
4. Keep the synthetic path working (it must still fire offline for path coverage).

### Acceptance criteria

- [ ] Dislocation is computed from executable prices (ask to buy, bid to sell).
- [ ] Each venue carries its true observation time.
- [ ] Quotes older than `max_quote_age_seconds` are excluded.
- [ ] A pair whose observation times differ by more than the skew limit is rejected.
- [ ] With realistic tight books, the arb plugin proposes **nothing** (the honest result).
- [ ] Config keys documented in `specs/OPERATIONS.md`; no magic numbers (C4).

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-002.1 | Wide mid gap, but ask/bid overlap | dislocation ≈ 0 → **no trade** (catches Bug A) |
| T-002.2 | Genuine executable gap | dislocation = `bid_rich − ask_cheap`, trade proposed |
| T-002.3 | One venue quote 30s old | that venue dropped |
| T-002.4 | Only 1 fresh venue remains | returns `None` |
| T-002.5 | Venue skew above limit | pair rejected |
| T-002.6 | Realistic 2 bps book across 3 venues | no proposal after costs |
| T-002.7 | Synthetic snapshot | still fires (offline coverage preserved) |
| T-002.8 | Regression: 30 bps mid gap, 35 bps spreads | **no trade** — this is the exact live failure |

**Extend:** `tests/test_cross_exchange_arb.py`

---

## T-003 ⬜ 12-month history + costed walk-forward backtest

**Priority:** P0 · **Blocked by:** T-001, T-002 · **Est:** L

### Why

`aimos/runtime/golive.py:22` defines the first gate as:

```python
("backtest_validated", "Validated 12-month backtest", "manual",
 "Permutation p<0.05, bootstrap CI, benchmarks beaten (§9.3/§20.2)", None)
```

`"manual"` = a human ticks a box. Nothing verifies it — and `specs/STATUS.md`
lists the 12-month dataset as **not built**, so the backtest it refers to has
never run. This gate cannot honestly be ticked today.

This is the task that converts every open question in this repo from opinion into
data: does *any* strategy have edge? Is the config worth fitting? Is a forecaster
worth building?

### Implementation

1. Run `scripts/download_history.py` (Binance publishes free klines at
   `data.binance.vision`) for the universe, 12 months, all traded timeframes.
2. Verify with `scripts/dataset_integrity.py`.
3. Walk-forward backtest via `aimos/backtest/engine.py`, **costs mandatory**
   (`config/costs.yaml`: 7.5 bps taker, 2.0 bps slip — ≈19 bps round trip).
4. Produce a per-strategy run card: trades, win rate, PnL, Sharpe, max DD, MAE/MFE
   distribution, and permutation p-value + bootstrap CI (`backtest/validation.py`).

### Acceptance criteria

- [ ] ≥ 12 months of candles for every Tier-1 symbol; integrity check green.
- [ ] Walk-forward only — `assert_temporal_split` enforced, no random split.
- [ ] Costs applied to every fill; a cost-free run is not acceptable output.
- [ ] Per-strategy run card committed under `specs/runcards/`.
- [ ] An explicit written verdict per strategy: **edge / no edge / insufficient sample**.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-003.1 | Backtest with costs vs without | costed PnL strictly lower — proves costs applied |
| T-003.2 | Shuffled labels | edge collapses to ~0 (guards against lookahead) |
| T-003.3 | Walk-forward split | no train timestamp ≥ any test timestamp |
| T-003.4 | Permutation test | p-value computed and reported per strategy |
| T-003.5 | Strategy with 0 trades | reported as "insufficient sample", never as "no edge" |
| T-003.6 | Dataset gaps | synthetic bars flagged and excluded from volume math |

**New test file:** `tests/test_backtest_validation.py`

---

## T-004 ⬜ Per-strategy attribution from real outcomes

**Priority:** P0 · **Blocked by:** T-001 · **Est:** S

### Why

`/api/performance` and `/api/strategies` (`aimos/api/server.py:403,507`) and the
AI analyst (`specs/ASSISTANT.md:58` — *"Which strategy is pulling its weight?"*)
are all built and all read outcome data that has never existed. They work; they
have nothing to say. Once T-001 lands they light up with no new UI work.

### Acceptance criteria

- [ ] Win rate, PnL, expectancy, and trade count per strategy, computed from `outcomes`.
- [ ] Sample-size caveat surfaced when n < 30 (per `ASSISTANT.md` guidance).
- [ ] The analyst's grounding bundle includes real per-strategy stats.
- [ ] Attribution stays **advisory** — nothing auto-disables a strategy (§15.3).

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-004.1 | 10 outcomes across 3 strategies | per-strategy counts and PnL correct |
| T-004.2 | n < 30 | response carries the low-sample caveat |
| T-004.3 | Zero outcomes | endpoint returns empty, does not crash or fabricate |
| T-004.4 | Losing strategy | reported, **not** auto-disabled |

---

# P1 — correctness and safety

## T-010 ⬜ Fit config parameters to real data

**Priority:** P1 · **Blocked by:** T-003 · **Est:** M

`config/observation.yaml` states in its own header that its values are *"initial
values"*. RSI 14/70/30, MACD 12/26/9, EMA 50 are textbook defaults, never fitted
to crypto or to this universe. `aimos/learning/optimize.py` and
`config/optimize_space.yaml` exist for exactly this and have never been run on
real data.

**Acceptance:** walk-forward parameter fit; out-of-sample improvement over
defaults; overfitting guard (parameter stability across folds reported).

| ID | Test | Assert |
|---|---|---|
| T-010.1 | Optimizer on synthetic noise | finds no stable edge (overfit guard works) |
| T-010.2 | Fitted vs default params, out-of-sample | improvement reported honestly, incl. if negative |
| T-010.3 | Fold-to-fold parameter variance | reported; high variance flagged as unstable |

---

## T-011 ⬜ Verify the go-live gate is honestly tickable

**Priority:** P1 · **Est:** S

`backtest_validated` is a manual checkbox with no verification. Add a guard that
refuses the tick unless a run card exists with permutation p < 0.05.

| ID | Test | Assert |
|---|---|---|
| T-011.1 | Tick gate with no run card | rejected |
| T-011.2 | Tick with p ≥ 0.05 run card | rejected |
| T-011.3 | Tick with valid run card | accepted |
| T-011.4 | Gates ticked out of order | rejected (existing ladder rule holds) |

---

# P2 — test coverage gaps

Measured by cross-referencing all 135 modules against all 71 test files for both
dotted-path imports and public-symbol references. **18 modules have no or weak
coverage.** Each gets one task below.

| ID | Module | State | Priority | Risk if wrong |
|---|---|---|---|---|
| T-030 ⬜ | `intelligence/finalize.py` | none | **P1** | Layer-2 output assembly — a bug here corrupts every `MarketUnderstanding` |
| T-031 ⬜ | `intelligence/explain.py` | none | P2 | Explainability is a §0 rule-4 requirement; untested |
| T-032 ⬜ | `execution/base_plugin.py` | none | **P1** | ABC + `estimate_costs_bps` — every plugin inherits it |
| T-033 ⬜ | `execution/plugins/funding_rate.py` | none | **P1** | Enabled strategy, zero direct tests |
| T-034 ⬜ | `execution/plugins/breakout.py` | weak | **P1** | Enabled strategy, referenced but not exercised |
| T-035 ⬜ | `execution/plugins/cross_exchange_arb.py` | weak | **P1** | The only strategy that fired; see T-002 |
| T-036 ⬜ | `execution/broker/base.py` | none | P2 | Broker ABC contract |
| T-037 ⬜ | `observation/scalp_micro.py` | none | **P1** | `scalp_enabled: true` by default — live and untested |
| T-038 ⬜ | `runtime/atomic_io.py` | none | **P1** | Atomic writes; the M8 audit fix lives here — a regression silently corrupts state |
| T-039 ⬜ | `auth/security.py` | none | **P1** | Auth primitives; C2 audit finding was an auth lockout |
| T-040 ⬜ | `auth/router.py` | weak (1/13) | **P1** | Login/JWT surface — the audit's Critical findings were both here |
| T-041 ⬜ | `data/store.py` | none | P2 | Parquet/DB read-write |
| T-042 ⬜ | `data/connectors/ccxt_connector.py` | none | P2 | Exchange adapter; needs a mocked-ccxt test |
| T-043 ⬜ | `storage/db.py` | none | P2 | Unified DB layer |
| T-044 ⬜ | `settings/config.py` | none | P2 | Encrypted settings |
| T-045 ⬜ | `learning/factor_select.py` | none | P2 | Factor selection |
| T-046 ⬜ | `learning/tax_export.py` | weak | P3 | Reporting only |
| T-047 ⬜ | `runtime/loop_process.py` | weak | P2 | REQ-13 process split |

### Standard test cases for every module task

Each of T-030..T-047 must cover, at minimum:

1. **Happy path** — normal inputs produce documented output.
2. **Empty/missing input** — returns a safe default; never raises (§10.1).
3. **Boundary values** — zero, negative, `None`, empty collection.
4. **Determinism** — same input twice → identical output.
5. **Config-driven** — no hardcoded tunables leak into behavior (C4).

### Additional per-module cases

**T-030 `finalize.py`** — every `MarketUnderstanding` field within its declared
bounds; `p_up ∈ [0,1]`; scores ∈ [0,100]; `reasons` non-empty (§0 rule 4).

**T-032 `base_plugin.py`** — `estimate_costs_bps` matches `config/costs.yaml`;
`can_trade` respects `required_regimes`; a plugin returning `None` is handled.

**T-033/T-034 plugins** — proposes when conditions met; returns `None` when not;
`expected_rr` ≥ configured minimum; stop is on the correct side of entry for both
long and short; no proposal when ATR is zero/missing.

**T-037 `scalp_micro.py`** — emits only registered evidence names; silent when the
book is thin; respects `max_spread_bps`.

**T-038 `atomic_io.py`** — a torn temp file never replaces a good file; no `.tmp`
left behind; concurrent writes do not interleave.

**T-039/T-040 auth** — wrong password rejected; token expiry enforced; lockout
after N failures **and** lockout release works (the C2 regression); no secret in
any log line or response body.

---

# P3 — Kronos forecasting sensor

Full requirements: **`specs/KRONOS_INTEGRATION.md`** (KR-1..KR-43).

| ID | Phase | Task | Blocked by |
|---|---|---|---|
| T-020 ⬜ | K0 | Operator sign-off: 4 evidence names + model-size ceiling | — |
| T-021 ⬜ | K1 | Quantizer + model + numpy inference + offline trainer | T-003 (needs data) |
| T-022 ⬜ | K2 | `ForecastEngine` behind flag, reliability 0.35 | T-001, T-021 |
| T-023 ⬜ | K3 | Anomaly evidence + dashboard fan chart | T-022 |
| T-024 ⬜ | K4 | Scenario generator + analyst grounding | T-022 |
| T-025 ⬜ | K5 | Re-evaluate ML/regime/universe routes | T-022 + shadow data |

**T-020 is the only one startable today**, and it is a decision, not code.

> **Hard sequencing note.** K2's exit gate (KR-31) requires *"directional IC > 0
> with costs applied"* over a 2-week shadow window. Computing an IC requires
> outcomes. **T-001 is therefore a hard blocker on the entire Kronos programme** —
> not a nice-to-have. Building the forecaster before the loop closes produces a
> model nobody can score.

---

## Recommended order

1. **T-001** — closes the loop. Unblocks the most per unit of work.
2. **T-002** — small, self-contained, fixes a real bug in the only firing strategy.
3. **T-003** — the big one. Answers "does any of this work?"
4. **T-030, T-032, T-037, T-038, T-039, T-040** — P1 coverage on live, risky paths.
5. **T-004, T-010, T-011** — attribution and honest gates.
6. **T-020 → T-025** — Kronos, once there is something to measure it against.
