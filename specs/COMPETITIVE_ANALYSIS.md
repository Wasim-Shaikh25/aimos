# COMPETITIVE_ANALYSIS — what to borrow from the major OSS trading platforms

**Source:** *Quantitative Evaluation and Empirical Synthesis of Open-Source
Automated Trading Frameworks* (operator-supplied, 2026-08).

**Purpose:** for each platform — is its code legally usable here, what exactly is
worth taking, where does it live upstream, and which AIMOS flow does it improve.

**Status:** analysis only. Nothing has been copied, vendored, or added.

> **On line numbers.** File paths are the durable reference; line numbers are
> approximate and drift with upstream commits. Every citation below gives the
> path first. Verify the line before relying on it.

---

## 1. Licence verdict — read this first

AIMOS has a hard rule: *"No copyleft (GPL/AGPL) package is imported into
`aimos/`"*, and already carries GPL debt in `vendor/GPL_TRIPWIRE.md` (two
freqtrade-derived files, tracked as T-005). So licence gates everything.

| Platform | Licence (**verified**) | PDF claimed | Verdict |
|---|---|---|---|
| **QuantConnect LEAN** | **Apache 2.0** | Apache 2.0 ✓ | ✅ **Code borrowable** with attribution |
| **Hummingbot** | **Apache 2.0** | Apache 2.0 ✓ | ✅ **Code borrowable** (already vendored as `vendor/hb_mm`) |
| **Passivbot** | **Unlicense** (public domain) | *MIT* ✗ | ✅ **Code borrowable**, no conditions at all |
| **NautilusTrader** | **LGPL-3.0** | LGPL-3.0 ✓ | ⚠️ **Concept only** — see §1.1 |
| **Freqtrade / FreqAI** | **GPL-3.0** | GPLv3 ✓ | ❌ **Concept only** — already our tripwire debt |
| **Abu (bbfamily)** | **GPL-3.0** | *"Open Source"* ✗ | ❌ **Concept only** |
| **OpenAlgo** | **AGPL-3.0** | *"Open Source"* ✗ | ❌❌ **Avoid entirely** — see §1.2 |

> **The PDF's licence column is unreliable.** Three of seven entries are wrong,
> and all three errors understate the restriction — Passivbot is freer than
> claimed, but Abu and OpenAlgo are *copyleft* where the PDF says only "Open
> Source". For a codebase with a hard no-copyleft rule, taking that column at face
> value would have introduced exactly the debt T-005 exists to retire. **Verify
> licences at the repository, never from a summary.**

### 1.1 NautilusTrader and LGPL — the nuance

LGPL-3.0 is *weak* copyleft. Using it as an unmodified library (pip dependency,
dynamic linking) does not force AIMOS to become LGPL; **copying its source into
`aimos/` does**. AIMOS's rule names "GPL/AGPL" specifically, so a pip dependency
is arguably permitted by the letter of the rule — but §21.1 says a wanted
capability from copyleft code runs as an isolated out-of-process service.

**Recommendation:** treat NautilusTrader as **read-for-ideas only**. Its value to
us is architectural (§4), and none of it requires their code. If we ever want the
engine itself, that is a PD3-style documented decision, not a quiet `pip install`.

### 1.2 OpenAlgo and AGPL — hard no

AGPL-3.0's network-use clause means *offering the software over a network* counts
as distribution, triggering source-disclosure obligations. `scripts/check_gpl_tripwire.py`
already names AGPL as "the current concrete risk" (its regex catches
`openbb|gpl|agpl|gnu`). AIMOS runs a web dashboard. **Do not read OpenAlgo's
source with intent to reimplement, do not vendor it, do not depend on it.** Its
distinguishing features (34 broker adapters, ₹1 Crore sandbox) are Indian-broker
specific and of no use to a crypto system anyway.

---

## 2. QuantConnect LEAN — the highest-value source ✅ Apache 2.0

Repo: `https://github.com/QuantConnect/Lean`

### 2.1 ⭐ `TradeBuilder` — the exact algorithm T-001 needs

**Files:** `Common/Statistics/Trade.cs` · `Common/Statistics/TradeBuilder.cs`

This is the single most directly applicable find in the whole review. `specs/TASKS.md`
T-001 needs MAE/MFE tracking, and LEAN has a mature, permissively-licensed
implementation of precisely that.

`Trade.cs` fields (~lines 31–153):

| Property | ~Line | Meaning | AIMOS `OutcomeRecord` |
|---|---|---|---|
| `EntryTime` / `EntryPrice` | 64 / 70 | open time, avg entry | ✅ have |
| `ExitTime` / `ExitPrice` | 88 / 94 | close time, avg exit | ✅ have |
| `ProfitLoss` | 100 | gross P&L in account currency | ✅ `pnl_quote` |
| `TotalFees` | 106 | total fees, always positive | ⚠️ netted into `pnl_quote`, not separate |
| **`MAE`** | **112** | **Maximum Adverse Excursion** | ⚠️ field exists, **never populated** |
| **`MFE`** | **118** | **Maximum Favorable Excursion** | ⚠️ field exists, **never populated** |
| `Duration` | 124 | trade duration | ❌ **missing** |
| **`EndTradeDrawdown`** | **132** | **profit given back before close** | ❌ **missing entirely** |
| `IsWin` | 141 | profitable or not | derivable |

**The MAE/MFE mechanism** (`TradeBuilder.cs`):

- `SetMarketPrice(Symbol, decimal)` (~line 152) is called on every price update. It
  walks pending trades and maintains `position.MinPrice` / `position.MaxPrice`
  across the position's life.
- At close (~line 334):
  ```csharp
  trade.MAE = Math.Round((trade.Direction == TradeDirection.Long
      ? position.MinPrice - trade.EntryPrice
      : trade.EntryPrice - position.MaxPrice) * trade.Quantity ...);
  ```

**This validates the T-001 design and sharpens it.** Track `min_price`/`max_price`
per open position on each bar; compute MAE/MFE once at close. AIMOS's
`PaperBroker.step()` (`aimos/execution/broker/paper.py:142`) already receives every
bar and already has `bar["high"]`/`bar["low"]` — the hook point exists.

> **Warning worth inheriting.** LEAN's `FlatToFlat` (~line 378) and `FlatToReduced`
> (~line 472) grouping modes **set MAE/MFE to zero** because multi-fill tracking is
> hard. Only `FillToFill` (~line 293) computes them. AIMOS's paper broker holds one
> position per symbol (`_positions: dict[symbol, Position]`), so we are in the
> `FillToFill` case and can compute them honestly — but if partial fills are ever
> added, this is where the metric silently degrades.

**Action:** fold into **T-001**. Add `duration` and `end_trade_drawdown`. Note that
adding fields to `OutcomeRecord` touches `schemas.py` → human approval (T-001 must
either request it or carry the extras in a side table).

### 2.2 ⭐ `PortfolioStatistics` — what T-003 should report

**File:** `Common/Statistics/PortfolioStatistics.cs`

Compared against `aimos/backtest/metrics.py` (which has Sharpe, Sortino, max
drawdown, hit rate, avg R, profit factor):

| LEAN statistic | ~Line | AIMOS | Verdict |
|---|---|---|---|
| `SharpeRatio` | 107 | ✅ `_sharpe` | have |
| `SortinoRatio` | 118 | ✅ `_sortino` | have |
| `Drawdown` | 85 | ✅ `max_drawdown` | have |
| `WinRate` / `LossRate` | 49 / 57 | ✅ hit rate | have |
| `ProfitLossRatio` | 43 | ✅ `profit_factor` | close enough |
| **`ProbabilisticSharpeRatio`** | **115** | ❌ | ⭐ **take this** |
| **`Expectancy`** | **65** | ❌ | ⭐ **take this** |
| `ValueAtRisk99` / `95` | 144 / 151 | ✅ in `risk/analytics.py` | have |
| `Alpha` / `Beta` | 133 / 128 | ✅ in `risk/analytics.py` | have |
| `InformationRatio` / `TrackingError` | 164 / 170 | ❌ | optional |
| `TreynorRatio` | 177 | ❌ | skip |

**Probabilistic Sharpe Ratio is the important one.** LEAN defines it as *"the
probability that the estimated Sharpe ratio is greater than a benchmark"*. That is
**exactly** the question T-003 exists to answer — "is this edge real, or is it noise
in a small sample?" A raw Sharpe of 1.4 over 30 trades and over 3,000 trades are
completely different claims, and only PSR distinguishes them. Given that the
current repo state has *zero* scored trades, this is the metric that will stop us
fooling ourselves first.

**`Expectancy`** = `WinRate × ProfitLossRatio − LossRate` (~line 65) — the single
number for "what do I make per trade on average," which profit factor does not give.

**Action:** new task **T-007**, feeding T-003's run card.

### 2.3 `MarketImpactSlippageModel` — a better cost model

**File:** `Common/Orders/Slippage/MarketImpactSlippageModel.cs`

Implements **Almgren et al. (2005)** market impact (~lines 26–29):

- Permanent impact `G(nu) = γ · nu^α`, temporary `H(nu) = η · nu^β` (~lines 137–149)
- Calibrated constants (~lines 69–76): `alpha=0.891`, `beta=0.600`, `gamma=0.314`,
  `eta=0.142`, `delta=0.267`
- Inputs: `nu` = order volume / average daily volume, `Sigma` = 252-day volatility,
  10-day average volume, execution time
- Realized impact = `temporary + 0.5 × permanent` (~lines 115–122)

AIMOS's model (`config/costs.yaml`) is **linear**: `slip_base_bps: 2.0`,
`slip_k: 25`, with `volume_proxy_depth_frac: 0.05`. Real impact is a power law —
it grows with roughly the square root of participation, so a linear model
*understates* the cost of large orders and *overstates* small ones.

**Caveats before adopting:** these constants are calibrated on **US equities**, not
crypto. `delta` uses shares outstanding, which has no crypto analogue. Take the
**functional form** (power law), refit the constants, or at minimum document that
the linear model is a known simplification.

**Action:** new task **T-008**. Directly affects whether T-003's numbers are honest.

### 2.4 The five-handler architecture — informational only

`IDataFeed`, `ITransactionHandler`, `IResultHandler`, `IRealtimeHandler`,
`ISetupHandler`. AIMOS already has the equivalent separation via its layered
`data → observation → intelligence → execution` contract with import-linter
enforcement — arguably stricter, since LEAN's is convention and ours is mechanical.
**Nothing to take.**

---

## 3. Hummingbot — executor patterns ✅ Apache 2.0

Repo: `https://github.com/hummingbot/hummingbot` · already partially vendored at
`vendor/hb_mm` (Avellaneda–Stoikov market-making math).

### 3.1 `DCAExecutor` — mostly a confirmation, not a gap

**File:** `hummingbot/strategy_v2/executors/dca_executor/dca_executor.py`

Its `control_barriers()` (~lines 251–261) evaluates protections in strict order:

| Hummingbot barrier | ~Line | AIMOS equivalent |
|---|---|---|
| Stop-loss | 263–276 | ✅ `TradeManager` + `risk_manager.py` |
| Trailing stop | 278–295 | ✅ `trail_activate_r: 1.5`, `trail_atr_mult: 1.2` |
| Take-profit | 297–303 | ✅ `partial_tp_r`, plugin TP |
| Time limit | 305–308 | ✅ `time_stop_hold_mult: 2.0` |

**Verdict: AIMOS already matches this, and in one respect beats it.** Our
`trade_manager.py` docstring specifies *"trailing stop (never widens)"* — a
monotonicity invariant that prevents a trailing stop from ever loosening. That is a
genuinely stronger guarantee than a dynamically-adjusting trigger.

**Worth taking:** the **retry/failed-order state machine**. `_failed_orders` with
`evaluate_max_retries()` (~lines 362–366) and `process_order_failed_event()`
(~lines 380–420) handle exchange rejections explicitly. AIMOS's
`stale_cancel_candles: 3` handles unfilled orders but not *rejected* ones — a real
gap on the live path, where rejections are routine.

**Action:** new task **T-009** — order-rejection handling on the live broker path.

### 3.2 Multi-level entry tracking

`_open_orders` / `_close_orders` / `_failed_orders` (~lines 50, 65–66) with
`n_levels` (~line 54) for laddered entries. AIMOS's `smart_dca` plugin is simpler.
Only worth revisiting if DCA becomes a primary strategy — **low priority**.

---

## 4. NautilusTrader — ideas only ⚠️ LGPL-3.0

Repo: `https://github.com/nautechsystems/nautilus_trader`
**Do not copy code.** Read for design.

### 4.1 `Position` — three fields worth having

**File:** `nautilus_trader/model/position.pyx`

| Field | ~Line | Meaning | AIMOS |
|---|---|---|---|
| `peak_qty` | 65–80 | max quantity reached | ❌ |
| `avg_px_open` / `avg_px_close` | 65–80 | avg prices across fills | partial |
| `realized_pnl` | 82 | accumulated realized P&L | ✅ `pnl_quote` |
| **`realized_return`** | **83** | `(close−open)/avg_px_open`, side-aware (`_calculate_return`, ~859–864) | ❌ — we have `pnl_r` (R-multiple), a *different* thing |
| **`duration_ns`** | 65–80 | open→close duration | ❌ **missing** |
| `commissions` | 76 | per-currency commission dict | ⚠️ netted |

`realized_return` (% return) and `pnl_r` (multiples of initial risk) answer
different questions. Having both lets you separate *"was the trade efficient?"*
from *"was the risk well sized?"* — worth adding alongside `duration`.

### 4.2 Backtest–live parity — the principle, already partly ours

Nautilus's headline claim is identical event processing across backtest and live,
so a strategy deploys unchanged. AIMOS has a **separate** backtester
(`aimos/backtest/engine.py`) and paper broker (`execution/broker/paper.py`) — two
codepaths that *could* drift.

We are not naive about it: `Clock` already abstracts live vs backtest time, and
T-001.9 explicitly tests that both journal identical outcome rows. **The principle
to adopt is the test discipline, not the architecture** — every shared behaviour
gets a parity test. Rewriting AIMOS around an event bus for this would be a
disproportionate change to a system whose determinism is already enforced.

### 4.3 Order types — deferred, correctly

IOC, FOK, GTC, GTD, post-only, reduce-only, iceberg, OCO/OTO/OUO. AIMOS uses
market/limit with `post_only` for scalps (`config/scalp.yaml:order_type: post_only`).

**Genuinely useful when live:** `reduce_only` (prevents an exit accidentally opening
a reverse position — a real safety property) and OCO (atomic SL/TP pairing;
without it, both can briefly rest, and a double-fill leaves an unintended position).

**Action:** new task **T-012**, blocked on live trading being reachable at all.
Not urgent while paper-only.

---

## 5. Freqtrade / FreqAI — ideas only ❌ GPL-3.0

Repo: `https://github.com/freqtrade/freqtrade`
We already carry freqtrade GPL debt (T-005). **Do not add more.** Concepts only.

### 5.1 FreqAI adaptive retraining

**File:** `freqtrade/freqai/freqai_interface.py`

| Mechanism | ~Line | What it does |
|---|---|---|
| `start()` | 134 | routes live vs backtest |
| `start_live()` | 379 | `check_if_new_training_required(trained_timestamp)` vs `live_retrain_hours` |
| `start_scanning()` / `_start_scanning()` | 197 / 204 | **background thread** consuming a `train_queue`, rotating pairs — retrains without blocking inference |
| `start_backtesting()` | 288 | **sliding window**: `tr_train` (e.g. 1 month) then `tr_backtest` (e.g. 1 week), advancing together |
| `buffer_timerange()` | — | **prepends a buffer before `tr_train` so indicators warm up without contaminating the split** |
| `define_data_pipeline()` | 554 | outlier removal: SVM, DBSCAN, Dissimilarity Index |
| `data_cleaning_predict()` | 983 | computes DI at predict time to flag out-of-distribution inputs |

**Three ideas worth having:**

1. **`buffer_timerange()` — the anti-lookahead detail.** Indicators like EMA(50) or
   ATR(100) need warmup bars. If warmup is taken from *inside* the training window
   you lose data; if from the test window you leak. A dedicated buffer *before* the
   train window solves it cleanly. This is directly relevant to **T-003** and to
   Kronos **KR-19**, and it is the kind of bug that silently inflates every result.
2. **Dissimilarity Index at predict time.** A live feature vector far from the
   training distribution means the model is extrapolating. AIMOS has PSI drift
   detection (§23.7) but that is *batch* monitoring — DI is *per-prediction*. It
   maps naturally onto `MLEngine.opine()` returning reduced confidence when the
   input is out-of-distribution, and onto Kronos KR-27's calibration requirement.
3. **Background retraining thread.** AIMOS trains one-shot via
   `scripts/train_from_history.py`. Continuous retraining is the natural successor —
   but note it is **gated on T-001**: retraining needs labels, labels need outcomes.

**Action:** new tasks **T-013** (buffer_timerange in the backtest split) and
**T-014** (DI-style OOD confidence reduction).

### 5.2 Documented weaknesses — reasons *not* to copy

The PDF reports, and upstream issues confirm: Freqtrade is candle/indicator-based,
**not** architected for order-book market making or two-sided grids; and community
testing finds rule-based strategies struggle in prolonged bear markets without
strict stops, leverage control, or shorting.

Both are conditions AIMOS already handles better — a mandatory `RiskOff` do-nothing
baseline, an enforced go-live ladder, and `NoTrade` as the default decision. Worth
recording so nobody proposes importing strategy logic wholesale.

---

## 6. Passivbot — risk ideas ✅ Unlicense (public domain)

Repo: `https://github.com/enarjord/passivbot` · `src/`, `passivbot-rust/`

**Freest licence in the set** — public domain, no attribution required.

**Do NOT take:** the core martingale grid — *"small initial entry and double down
on losing positions multiple times."* Averaging into losers is exactly what
AIMOS's risk manager and R-multiple sizing exist to prevent. Directly contrary to
`daily_scalp_stop_r: -3.0` and `consecutive_loss_pause: 3`.

**DO consider — two risk ideas:**

1. **The "unstucking" protocol.** When positions are underwater, realize small
   losses *incrementally*, prioritizing the position with the smallest
   entry-to-market spread (cheapest to exit). AIMOS's `risk_manager.py` has
   portfolio heat caps and a killswitch, but no *graceful de-risking ladder* — it is
   closer to all-or-nothing. A staged reduction is gentler and more realistic.
2. **Wallet exposure vs peak balance.** Constrain drawdown relative to *peak
   historical* balance, not just current equity. AIMOS tracks drawdown in metrics
   but does not use peak-relative exposure as a live *sizing constraint*.

**Action:** new task **T-015** (evaluate staged de-risking + peak-relative exposure
cap). Design-first; both interact with the risk manager and need care.

---

## 7. Abu ❌ GPL-3.0 · OpenAlgo ❌❌ AGPL-3.0 — skip both

**Abu** — Chinese A-share focused (`abupy`), GPL-3.0. Its ML feature-extraction and
portfolio-allocation ideas are not differentiated enough to justify GPL exposure
when LEAN (Apache) covers the same ground. **Skip.**

**OpenAlgo** — AGPL-3.0, network-use clause, and AIMOS serves a web dashboard. Its
34 broker adapters are Indian securities brokers; its ₹1 Crore sandbox is a paper
mode AIMOS already has. **Zero value, maximum licence risk. Do not read with intent
to reimplement.**

One idea is worth noting *independently* of their code, because it is generic: they
run the sandbox on a **separate database for complete isolation**. AIMOS keeps paper
and live state in the same `state/aimos.sqlite`. Whether that matters is a real
question — filed as **T-016** to evaluate, owing nothing to their implementation.

---

## 8. Summary — what we take, and what we already do better

### Adopt (7 concrete items)

| # | Item | Source | Licence | Improves |
|---|---|---|---|---|
| 1 | **MAE/MFE algorithm** (`min_price`/`max_price` → compute at close) | LEAN `TradeBuilder.cs` | Apache ✅ | **T-001** |
| 2 | **`EndTradeDrawdown`** + `Duration` | LEAN `Trade.cs` | Apache ✅ | T-001 |
| 3 | **Probabilistic Sharpe Ratio** + **Expectancy** | LEAN `PortfolioStatistics.cs` | Apache ✅ | **T-003** (T-007) |
| 4 | **Power-law market impact** | LEAN `MarketImpactSlippageModel.cs` | Apache ✅ | T-003 cost honesty (T-008) |
| 5 | **`buffer_timerange()`** anti-lookahead warmup | FreqAI | GPL — *concept* | T-003, Kronos KR-19 (T-013) |
| 6 | **Dissimilarity Index** OOD confidence | FreqAI | GPL — *concept* | MLEngine, Kronos KR-27 (T-014) |
| 7 | **Order-rejection retry state** | Hummingbot `dca_executor.py` | Apache ✅ | live path (T-009) |

### Consider

`realized_return` + `duration` on outcomes (Nautilus, LGPL — concept) · staged
de-risking and peak-relative exposure (Passivbot, Unlicense) · `reduce_only` and
OCO order types when live (Nautilus) · separate paper/live databases (generic).

### Reject

Martingale grid (Passivbot) — contrary to our risk model · Freqtrade strategy logic
(GPL + documented bear-market weakness) · OpenAlgo entirely (AGPL) · Abu (GPL, no
differentiation) · rewriting around an event bus for parity (disproportionate).

### Where AIMOS is already ahead

Worth stating, because several of these platforms are far more popular and it would
be easy to assume they are better across the board:

| Capability | AIMOS | The field |
|---|---|---|
| Trade management barriers | breakeven, trailing **that never widens**, partial TP, thesis exit, time stop, stale sweep | Hummingbot comparable; Freqtrade weaker |
| Architectural enforcement | import-linter **mechanically** enforces layer direction | LEAN's is convention |
| Audit trail | SHA-256 **hash-chained** journal | none of the seven |
| Fail-closed live path | mandate + go-live ladder + boot guard | none comparable |
| Determinism as a rule | no LLM in decision path, all time via `clock.now()`, no magic numbers | Nautilus only, and only on latency |
| Default decision | **`NoTrade` is always valid and default** | most default to acting |

The gap is not architecture. It is **measurement** — which is what T-001 and T-003
address, and what items 1–4 above make sharper.

---

## 9. New tasks generated

Added to `specs/TASKS.md`:

| ID | Task | Priority | Blocked by |
|---|---|---|---|
| T-007 | Probabilistic Sharpe + Expectancy in backtest metrics | P1 | — |
| T-008 | Power-law market-impact slippage model | P1 | — |
| T-009 | Order-rejection retry handling on live path | P1 | — |
| T-012 | `reduce_only` + OCO order types | P2 | live path |
| T-013 | `buffer_timerange` anti-lookahead warmup in splits | **P0** | — |
| T-014 | Dissimilarity-Index OOD confidence reduction | P2 | T-001 |
| T-015 | Staged de-risking + peak-relative exposure cap | P2 | design review |
| T-016 | Evaluate separate paper/live state isolation | P3 | — |

**T-013 is P0**: an indicator-warmup leak would silently inflate every number T-003
produces, and T-003 is the task everything else depends on. It must be correct
*before* the backtest runs, not diagnosed after.
