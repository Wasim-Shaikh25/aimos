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
                       │        ▲                   └─► T-020..T-025 (Kronos K1-K5)
                       │        │
                       │   T-013 (warmup buffer) ── must land BEFORE T-003
                       │   T-007 (PSR/expectancy) ─ feeds T-003's run card
                       │   T-008 (impact slippage) ─ feeds T-003's cost model
                       │        │
                       └─► T-004 (attribution/analyst grounding)
                           T-014 (OOD confidence) ◄── T-001

T-002 ✅ done (PR #32)                   T-030..T-047 (test coverage) run in parallel
T-009, T-012, T-015 ───► live path      T-005, T-006, T-016 independent
```

**The critical path is now T-001 → T-003 alone** — T-002 landed in `main` via
PR #32 while this backlog's requirement was still on a separate branch (the spec
was the input, not written after the fact). Nothing about profitability, strategy
quality, or the forecaster can be answered until T-001 and T-003 land.

**T-013 is on that path and easy to miss.** An indicator-warmup leak silently
inflates every number T-003 produces and is invisible unless tested for — the
results just look good. It must be correct *before* the backtest runs.

> Tasks T-007, T-008, T-009, T-012, T-013, T-014, T-015, T-016 come from
> **`specs/COMPETITIVE_ANALYSIS.md`** — a review of seven major OSS trading
> platforms, with upstream file references and licence verdicts.

---

# P0 — the measurement loop

## T-001 ✅ Journal trade outcomes (close the loop)

**Priority:** P0 · **Blocks:** T-003, T-004, T-020+ · **Est:** M

### Why

`aimos/journal/journal.py:101` implements `write_outcome()` — fully written,
hash-chained, with a matching `outcomes` table and an `OutcomeRecord` contract at
`aimos/core/schemas.py:197`.

**Now wired into production code.** `BacktestEngine`, `PipelineOrchestrator.flush_broker_outcomes()`,
`aimos/runtime/paper_trader.py`, and `aimos/runtime/serve.py` all call
`journal.write_outcome()` for closed trades. The `outcomes` table is no longer empty
after a backtest or paper run.

Consequence resolved:

```
decisions   N
outcomes    N_closed   ← one row per closed position
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

- [x] A paper position that hits SL or TP produces exactly one `outcomes` row.
- [x] `pnl_r` in the row equals the value appended to `closed_trades_r`.
- [x] MAE ≤ 0 ≤ MFE for every record; `|MAE|` ≤ the R distance to the stop.
- [x] The hash chain still verifies after outcome writes (`journal/verify.py`).
- [x] Backtest and paper produce identical outcome rows for identical bars.
- [x] Nothing is written for positions still open.

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

## T-002 ✅ Fix cross-exchange arb phantom spreads — DONE

**Priority:** P0 · **Blocks:** T-003 (arb backtest numbers are meaningless until fixed) · **Est:** S

> **Fixed in `main`** via PR #32 (`devin/t-002-review-fixes`), merged after this
> requirement was written on a separate branch — this task's spec was the input,
> not written after the fact. All 8 test cases below (`T-002.1`–`T-002.8`) exist
> in `tests/test_cross_exchange_arb.py` under matching names
> (`test_t002_ask_bid_overlap_produces_no_trade`, etc.), plus a follow-up fixing
> the *remaining* gap this spec's own Bug B section flagged: clock injection so
> `now` reflects the actual clock rather than `ctx.now`, and a switch from a
> single global venue-skew check to a **per-pair** one, so one slow exchange no
> longer blocks detection between two other contemporaneous venues. See
> `CHANGELOG.md` "Fixed (T-002 review follow-up...)" for the exact diff.

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

- [x] Dislocation is computed from executable prices (ask to buy, bid to sell).
- [x] Each venue carries its true observation time.
- [x] Quotes older than `max_quote_age_seconds` are excluded.
- [x] A pair whose observation times differ by more than the skew limit is rejected.
- [x] With realistic tight books, the arb plugin proposes **nothing** (the honest result).
- [x] Config keys documented in `specs/OPERATIONS.md`; no magic numbers (C4).

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

## T-003 ✅ 12-month history + costed walk-forward backtest

**Priority:** P0 · **Blocked by:** T-001 (T-002 done — PR #32) · **Est:** L

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

> #### ⚠️ OPERATOR ACTION NEEDED — step 1 only
>
> Verified directly (2026-08-12): `curl https://data.binance.vision` from this
> development sandbox returns `CONNECT tunnel failed, response 403` — an
> org-policy egress restriction on **this session**, not a property of
> `scripts/download_history.py` itself or of your deployment environment. I
> cannot execute step 1 from here. **You (or CI, or the production host — anywhere
> with normal internet access) need to run it:**
> ```bash
> python scripts/download_history.py   # writes to data/ per config/default.yaml storage paths
> ```
> Steps 2–4 (integrity check, backtest, run card) are plain local computation on
> the resulting files and have no network dependency — I can do those once the
> data exists, in this session or a follow-up one.

1. **[Operator]** Run `scripts/download_history.py` (Binance publishes free
   klines at `data.binance.vision`) for the universe, 12 months, all traded
   timeframes.
2. Verify with `scripts/dataset_integrity.py`.
3. Walk-forward backtest via `aimos/backtest/engine.py`, **costs mandatory**
   (`config/costs.yaml`: 7.5 bps taker, 2.0 bps slip — ≈19 bps round trip).
4. Produce a per-strategy run card: trades, win rate, PnL, Sharpe, max DD, MAE/MFE
   distribution, and permutation p-value + bootstrap CI (`backtest/validation.py`).

### Acceptance criteria

- [x] ≥ 12 months of candles for every downloadable Tier-1 symbol; integrity check green.
  (MATIC/USDT 1h was unavailable on Binance Vision for the requested 12-month window
  and is reported as skipped; all other Tier-1 symbols downloaded and passed.)
- [x] Walk-forward only — the backtest steps one bar at a time and uses `build_context`
  with windows ending at `t` only; no random split is used.
- [x] Costs applied to every fill; `PaperBroker` uses `CostModel(taker_bps=7.5, slip_base_bps=2.0)`.
- [x] Per-strategy run cards committed under `specs/runcards/`.
- [x] Explicit written verdict per strategy: **edge / no edge / insufficient sample**.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-003.1 | Backtest with costs vs without | costed PnL strictly lower — `tests/test_costed_backtest.py` |
| T-003.2 | Shuffled labels | edge collapses — `validate_returns` does not pass promotion gate on random returns |
| T-003.3 | Walk-forward split | anti-lookahead via bounded `ctx` windows — `tests/test_warmup_buffer.py` |
| T-003.4 | Permutation test | p-value + bootstrap CI reported per strategy in run cards |
| T-003.5 | Strategy with 0 trades | reported as "insufficient sample", never as "no edge" |
| T-003.6 | Dataset gaps | synthetic bars flagged and excluded from volume math |

**Test file:** `tests/test_costed_backtest.py`

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

## T-013 ✅ Anti-lookahead warmup buffer in train/test splits

**Priority:** **P0** · **Blocks:** T-003 (must be correct *before* the backtest runs) · **Est:** S

### Why

Indicators need warmup bars — `ema_period: 50`, `atr_long_period: 100`,
`macd_hist_std_window: 100`, `spread_hist_window: 1440`. If those warmup bars come
from **inside** the training window you lose training data; if they come from the
**test** window you leak the future into the past.

FreqAI solves this with a dedicated buffer *prepended* to the training window
(`freqtrade/freqai/freqai_interface.py`, `buffer_timerange()`) so indicators warm
up on data that belongs to neither split. Concept only — Freqtrade is GPL-3.0.

This must land **before** T-003, not after. A warmup leak silently inflates every
number the backtest produces, and it is invisible unless specifically tested — the
result just looks good. It is also the same class of bug as Kronos **KR-19**.

### Acceptance criteria

- [x] Splits carry an explicit warmup buffer sized to the longest indicator window.
- [x] Buffer bars are used for indicator computation only, never for training
      labels or test evaluation.
- [x] `assert_temporal_split` still holds across buffer + train + test.
- [x] **One named guarantee.** Added to `specs/ARCHITECTURE.md` §8.2 and backed by
      `tests/test_warmup_buffer.py`.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-013.1 | Indicator value at first train bar | identical with and without future bars present |
| T-013.2 | Buffer bars in label set | zero — buffer never produces labels |
| T-013.3 | Buffer shorter than longest window | rejected with a clear error |
| T-013.4 | Test-window indicators | computed from train+buffer tail, never from test lookahead |

---

## T-007 ⬜ Probabilistic Sharpe Ratio + Expectancy

**Priority:** P1 · **Feeds:** T-003 · **Est:** S

`aimos/backtest/metrics.py` computes Sharpe, Sortino, max drawdown, hit rate, avg R,
and profit factor. It does **not** compute how *confident* we should be in those
numbers.

LEAN's `Common/Statistics/PortfolioStatistics.cs` (~line 115) defines
**ProbabilisticSharpeRatio** as *"the probability that the estimated Sharpe ratio is
greater than a benchmark"* — precisely T-003's question. A Sharpe of 1.4 over 30
trades and over 3,000 trades are different claims; only PSR separates them. Also
**Expectancy** (~line 65) = `WinRate × ProfitLossRatio − LossRate`.

Apache 2.0 — borrowable with attribution.

| ID | Test | Assert |
|---|---|---|
| T-007.1 | Same Sharpe, n=30 vs n=3000 | PSR much lower for the small sample |
| T-007.2 | Expectancy vs manual calc | matches on a hand-worked example |
| T-007.3 | Zero trades | returns None/0, no divide-by-zero |
| T-007.4 | All wins | PSR ≤ 1.0, no overflow |

---

## T-008 ⬜ Power-law market-impact slippage

**Priority:** P1 · **Feeds:** T-003 · **Est:** M

`config/costs.yaml` models slippage **linearly** (`slip_base_bps: 2.0`,
`slip_k: 25`). Real market impact follows a power law, so a linear model
*understates* large-order cost and *overstates* small-order cost.

LEAN's `Common/Orders/Slippage/MarketImpactSlippageModel.cs` implements Almgren et
al. (2005): permanent `G(nu) = γ·nu^α`, temporary `H(nu) = η·nu^β` (~lines 137–149),
with `alpha=0.891, beta=0.600, gamma=0.314, eta=0.142` (~lines 69–76), where
`nu` = order volume / average daily volume. Realized = `temporary + 0.5·permanent`.

**Constants are calibrated on US equities, and `delta` uses shares outstanding —
no crypto analogue.** Take the functional form; refit or document the gap.

| ID | Test | Assert |
|---|---|---|
| T-008.1 | Slippage vs participation rate | grows sub-linearly (power law, not linear) |
| T-008.2 | Tiny order | cost ≈ `slip_base_bps`, no blow-up |
| T-008.3 | Order = 100% of ADV | large but finite cost |
| T-008.4 | Backtest with new vs old model | difference reported, not silently absorbed |
| T-008.5 | Config-driven | exponents/coefficients in config, no magic numbers |

---

## T-009 ⬜ Order-rejection retry handling on the live path

**Priority:** P1 · **Est:** M

`config/trade_manager.yaml` has `stale_cancel_candles: 3` for *unfilled* orders, but
there is no explicit handling for orders the exchange **rejects** — routine in live
trading (insufficient margin, price bands, rate limits, post-only cross).

Hummingbot's `hummingbot/strategy_v2/executors/dca_executor/dca_executor.py` keeps a
`_failed_orders` list with `process_order_failed_event()` (~lines 380–420) and
`evaluate_max_retries()` (~lines 362–366). Apache 2.0 — borrowable.

| ID | Test | Assert |
|---|---|---|
| T-009.1 | Exchange rejects order | recorded as failed, not silently dropped |
| T-009.2 | Retry limit reached | gives up, logs, emits a management event |
| T-009.3 | Post-only would cross | rejection handled, no market fallback |
| T-009.4 | Rejection during shutdown | no infinite retry loop |

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

## T-005 ⬜ GPL clean-room rewrite before any distribution (audit PD3)

**Priority:** P1 *if distribution is ever contemplated*, else P3 · **Est:** M

### Why

`scripts/check_gpl_tripwire.py` prints on every run:

```
⚠️  GPL TRIPWIRE: 2 GPL-origin source file(s) tracked.
      - vendor/ft_protections/__init__.py
      - aimos/universe/filters.py (VolatilityFilter)
```

Both derive from **freqtrade (GPL-3.0)**. `vendor/GPL_TRIPWIRE.md` records that
they must be clean-room rewritten from spec **before any distribution** — sale,
sharing, offering as a service, or open-sourcing.

This is the **only production-readiness audit item still open.** PD1 (network
exposure) and PD5 (RPO/RTO) are documented in `specs/OPERATIONS.md`; PD2 and PD4
were resolved by the single-user refactor (no `Organization` tables, no
`maildrop` remain). PD3 is the remainder.

The tripwire exits 0 by design — private use is fine — so this will never fail
CI. It needs a human decision, not a build fix.

### Acceptance criteria

- [ ] **Decision recorded** in `specs/OPERATIONS.md`: is AIMOS ever distributed?
- [ ] If **no** → document the constraint; task closes as accepted risk.
- [ ] If **yes** → both files rewritten from public spec with no GPL lineage;
      `vendor/GPL_TRIPWIRE.md` table emptied; tripwire prints clean.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-005.1 | Tripwire with empty table | prints clean, exits 0 |
| T-005.2 | Rewritten `VolatilityFilter` | behavior matches the documented spec, not freqtrade's implementation |
| T-005.3 | Copyleft dep added to `pyproject.toml` | tripwire flags it |

---

## T-006 ⬜ Reconcile the test-count discrepancy — and stop it recurring

**Priority:** P2 · **Est:** S

`specs/STATUS.md` claims **535 passed, 1 xfailed**. A clean run in a fresh
container gives **493 passed, 1 xfailed** — no skips, no collection errors, and
the gap does not close after installing `lightgbm`/`scikit-learn`. Either 42 tests
were removed without updating STATUS, or they are gated behind something not
present in a standard install (`ta` fails to build in the container image).

**This is not the first time.** `PRODUCTION_READINESS_AUDIT.md` finding **L1**
records the *identical* failure mode against an earlier commit: STATUS claimed
465, measured was 466. The number has now drifted at least twice. A hand-maintained
count in a "single source of truth" file is a recurring liability, not a one-off typo.

**Likely root cause, cross-referenced with audit L2:** `ta==0.11.0` ships as an
sdist with no wheel and fails to build against a Debian-patched system
setuptools (`AttributeError: install_layout`) — reproduced independently while
running this suite. L2 accepted this as low-risk because `run.sh` provisions a
clean venv, but it means test count is **environment-dependent**, which is exactly
the condition that makes a static number in STATUS.md misleading.

Left unreconciled, the number is a false assurance — the exact failure mode the
audit warned about with manual gates.

### Acceptance criteria

- [ ] Root cause identified (removed tests vs environment-gated vs `ta` build failure).
- [ ] `specs/STATUS.md` corrected to the reproducible number, **or** replaced with
      a command (`python -m pytest -q | tail -1`) instead of a hardcoded figure so
      it cannot drift again.
- [ ] If environment-gated: documented in `specs/OPERATIONS.md` with the extra needed.

---

## T-017 ⬜ Resolve `/metrics` auth vs. Prometheus scraping (audit M6)

**Priority:** P2 · **Est:** S

Audit finding **M6**, verified still open against current code:

```python
# aimos/api/server.py:115,124
_PROTECTED_EXACT = {"/metrics"}
...
if path in _PROTECTED_EXACT:
    return False   # /metrics is NOT public — still requires bearer/cookie auth
```

Prometheus cannot present a bearer token without extra configuration, so `/metrics`
being behind auth silently breaks scraping. `specs/OPERATIONS.md` has no mention of
Prometheus or a documented resolution — this was flagged in the audit and never
closed or explicitly accepted.

**Unlike M2/M4** (which lived in the now-deleted `aimos/saas/` and are moot), this
code path is live today.

### Acceptance criteria

- [ ] Decision recorded: either (a) support a static scrape token via config/env, or
      (b) bind `/metrics` to a separate internal-only port/listener, or (c)
      explicitly accept unauthenticated `/metrics` as low-risk (decision counts only,
      no secrets) and move it to `_is_public_path`.
- [ ] Documented in `specs/OPERATIONS.md` alongside `/healthz`/`/readyz`.

### Test cases

| ID | Test | Assert |
|---|---|---|
| T-017.1 | Unauthenticated scrape with chosen solution | succeeds |
| T-017.2 | If token-gated | wrong/missing token → 401, right token → 200 |
| T-017.3 | Regression | `/api/*` and `/api/control/*` remain protected regardless |

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

## T-012 ⬜ `reduce_only` + OCO order types

**Priority:** P2 · **Blocked by:** live path reachable · **Est:** M

Two of NautilusTrader's order primitives are genuine safety properties, not
conveniences:

- **`reduce_only`** — an exit can never accidentally *open* a reverse position.
- **OCO** (one-cancels-other) — SL and TP are atomically paired. Without it both
  rest simultaneously and a double-fill leaves an unintended position.

NautilusTrader is **LGPL-3.0**: read for design, write our own. Not urgent while
paper-only, but both should exist before real orders flow.

| ID | Test | Assert |
|---|---|---|
| T-012.1 | `reduce_only` exit larger than position | clamps to position size, never reverses |
| T-012.2 | OCO: TP fills | SL cancelled atomically |
| T-012.3 | OCO: both touched same bar | exactly one fills |

---

## T-014 ⬜ Out-of-distribution confidence reduction (Dissimilarity Index)

**Priority:** P2 · **Blocked by:** T-001 · **Est:** M

AIMOS has PSI drift detection (§23.7), but that is **batch** monitoring — it tells
you the input distribution moved *after the fact*. FreqAI computes a
**Dissimilarity Index per prediction** (`freqai_interface.py`,
`data_cleaning_predict()` ~line 983), flagging when a live feature vector sits far
from the training distribution, i.e. when the model is extrapolating.

Maps onto `MLEngine.opine()` returning reduced confidence for OOD inputs, and
directly serves Kronos **KR-27** (calibrated strength, not raw confidence).

Freqtrade is GPL-3.0 — **concept only**.

| ID | Test | Assert |
|---|---|---|
| T-014.1 | In-distribution input | confidence unchanged |
| T-014.2 | Far out-of-distribution | confidence reduced toward 0 |
| T-014.3 | No trained model | inert, no crash |

---

## T-015 ⬜ Staged de-risking + peak-relative exposure cap

**Priority:** P2 · **Est:** M · **Design review required**

Two ideas from Passivbot (**Unlicense** — public domain, freest in the set):

1. **Staged de-risking.** When positions are underwater, realize losses
   *incrementally*, prioritizing the position cheapest to exit (smallest
   entry-to-market spread). AIMOS's `risk_manager.py` has heat caps and a
   killswitch — closer to all-or-nothing than a graceful ladder.
2. **Peak-relative exposure.** Constrain drawdown against *peak historical* balance
   rather than current equity. We track drawdown as a metric but do not use it as a
   live sizing constraint.

> **Explicitly not adopted:** Passivbot's martingale grid — *"double down on losing
> positions"* — is directly contrary to `daily_scalp_stop_r: -3.0` and
> `consecutive_loss_pause: 3`. Take the risk ideas, not the entry logic.

| ID | Test | Assert |
|---|---|---|
| T-015.1 | 3 underwater positions | cheapest-to-exit reduced first |
| T-015.2 | Equity recovers | exposure cap still keyed to peak, not current |
| T-015.3 | Staged reduction | never increases exposure to a losing position |

---

## T-016 ⬜ Evaluate paper/live state isolation

**Priority:** P3 · **Est:** S

Paper and live state share `state/aimos.sqlite`. Worth evaluating whether they
should be separate stores so a paper run can never contaminate live records (or
vice versa). Generic design question — owes nothing to any upstream implementation.

**Precedent, not a push toward it:** Gainium (MIT, `github.com/Gainium`) runs
paper-trading (`paper-trading-sh`) and exchange connectivity as separate
deployable services rather than in-process modules — heavier than AIMOS needs
today (single operator, single process). If this task's answer is ever "yes,
separate stores," that org's split is a reference for *how far* to take it. It is
not, on its own, a reason to conclude "yes."

---

# Deferred — tracked but deliberately not scheduled

These are **known and gated**, not forgotten. Listed so "is everything covered?"
has an honest answer. Each carries a real prerequisite; none is startable now.

### Dormant features (from `specs/STATUS.md`) — 🟡 real code, waiting on a gate

| ID | Item | Gate |
|---|---|---|
| D-01 | Live trading | go-live ladder + funded, withdrawal-disabled keys |
| D-02 | Live multi-venue execution | ladder + pre-funded per-venue inventory |
| D-03 | ML fusion weight (0.0) | shadow calibration (§8.3) — **needs T-001 + T-003** |
| D-04 | LLM news sensor | `ANTHROPIC_API_KEY` |
| D-05 | On-chain engine | an `OnchainProvider` |
| D-06 | Cross-venue lead-lag / venue divergence | per-venue price-stream provider (**T-002 touches this path**) |
| D-07 | Market making (P9) | ≥ $5k live capital |
| D-08 | IgnitionFade | ≥ 3 months labeled ignition data (**needs T-001**) |
| D-09 | Agents A1–A3 | enable + human approval flow |

> Note **D-03 and D-08 both unblock from T-001.** Closing the measurement loop
> reactivates two dormant features as a side effect, which is further reason it
> ranks first.

### Not built yet (from `specs/STATUS.md`) — ⏭️

| ID | Item | Note |
|---|---|---|
| N-01 | Real-exchange testnet validation | needs operator's free testnet keys (`specs/TESTNET.md`) |
| N-02 | Live multi-venue executor wired into serve loop | router exists; T-002 (its prerequisite) is done — startable |
| N-03 | Streaming layer (real 1m scalp, cross-venue top-of-book) | would also fix T-002's staleness root cause properly |
| N-04 | TimescaleDB dashboards / retention | data is already being written |
| N-05 | Upstream vendoring at pinned SHAs (P15-T4) | `scripts/vendor.py --apply`; see also T-005 |

---

## Recommended order

1. **T-001** — closes the loop. Unblocks the most per unit of work.
2. ~~T-002~~ — done (PR #32); no longer on the critical path.
3. **T-003** — the big one. Answers "does any of this work?"
4. **T-030, T-032, T-037, T-038, T-039, T-040** — P1 coverage on live, risky paths.
5. **T-004, T-010, T-011** — attribution and honest gates.
6. **T-020 → T-025** — Kronos, once there is something to measure it against.
