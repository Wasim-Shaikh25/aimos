# Changelog

Everything implemented, newest first. **Update this file after every change** —
one entry per meaningful unit of work (see `CLAUDE.md`). Format loosely follows
Keep a Changelog. Dates are the working session, not calendar-exact.

## Unreleased

### Added
- T-004: `aimos/journal/analytics.py` computes per-strategy attribution from
  journaled `outcomes` joined to `decisions`. `/_performance` now surfaces
  `from_outcomes` with win rate, PnL, expectancy, MAE/MFE, and a `low_sample`
  caveat when a strategy has fewer than 30 trades. `/api/strategies` includes the
  same per-strategy outcome block. The AI analyst grounding bundle sees real
  per-strategy stats via the existing `performance` provider.
- T-011: `GoLiveLadder.mark()` now refuses to tick `backtest_validated` unless
  `specs/runcards/` contains at least one run card with `validation.permutation_p`
  < 0.05. Gate order checks are still enforced. `runcards_dir` is an optional
  constructor argument (defaults to `specs/runcards`).

### Fixed (T-003 review follow-up — universe_snapshot_id was the trade count, not a data identity)
- `scripts/run_backtest_card.py`'s `universe_snapshot_id` was
  `f"{exchange}-tier1-{len(all_trades)}"` — the number of trades a strategy made,
  not an identifier for the candle data used. Two runs against different market
  data could get the same id if they happened to produce the same trade count,
  and the field could never actually confirm two runs used identical candles —
  defeating its own stated purpose.
- New `_candles_fingerprint()` hashes the actual OHLCV values fed to the run
  (`open`/`high`/`low`/`close`/`volume`, in order), reusing the existing
  `validation.data_hash()` utility. `universe_snapshot_id` is now
  `f"{exchange}-{symbol}-{timeframe}-{fingerprint}"` — genuinely content-addressed:
  identical data always hashes identically, any change to the data changes it.
- New regression test
  `test_universe_snapshot_id_is_a_real_data_fingerprint_not_trade_count` in
  `tests/test_costed_backtest.py` asserts both directions: same data (twice) →
  same fingerprint regardless of downstream trade count; different data, same
  row count → different fingerprint.
- **The 77 run cards already committed under `specs/runcards/` predate this fix**
  and still carry the old trade-count values in that field — noted in
  `specs/TASKS.md` T-003 rather than silently left stale. Regenerating them needs
  the 12-month dataset, which this session doesn't have
  (`specs/OPERATOR_ACTIONS.md` item 1); all future runs get the corrected field.

### Added (integration — combine all open PRs and PR #36 Kronos docs)
- Merged the currently open branches into the `devin/t-003-costed-backtest`
  integration branch: PR #30 (T-001 outcomes), PR #33 (T-002 clock follow-up),
  PR #34 (T-013 warmup), and PR #36 (Kronos download spec + `OPERATOR_ACTIONS.md`
  + T-002 reconciliation).
- Updated `specs/STATUS.md`, `specs/OPERATOR_ACTIONS.md`, and `specs/TASKS.md`
  after the merge: T-001/T-002/T-003/T-013 are ✅, the critical path is now
  T-001 → T-003 → T-010 with T-004 as the next P0, and Kronos K1-K5 remains
  gated by K0 operator sign-off.
- Streamlined `specs/TASKS.md` by sorting `## T-XXX` sections numerically within
  each priority group and removing stray duplicate-number occurrences (verified
  no actual duplicate task IDs remain).

### Added (T-003 — 12-month costed walk-forward backtest)
- New `scripts/run_backtest_card.py` downloads 12 months of Binance 1h klines for the
  offline Tier-1 universe, runs a costed walk-forward backtest per symbol, and
  writes per-strategy run cards to `specs/runcards/`.
- Run cards include trades, win rate, total PnL, Sharpe, max drawdown, MAE/MFE,
  permutation p-value, bootstrap Sharpe CI, and an explicit `edge / no edge /
  insufficient sample` verdict.
- `BacktestEngine.run()` now accepts an optional `peers` dict and bounds the
  observation window to the longest indicator lookback so 12-month replays stay
  O(n) instead of O(n²).
- Generated run cards for all 11 Tier-1 symbols with 12 months of data
  (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, TRX, DOT; MATIC had no
  2025-08..2026-07 1h files on Binance Vision).
- `scripts/download_history.py` now supports `--all` / `--top-n` /
  `--include-stable` to download 12 months of 1h candles for every currently
  trading Binance USDT spot pair (stablecoin bases excluded by default). This is
  the simple one-command script for building the full-asset history the user
  requested. The symbol list is fetched via `www.binance.com/api/v3` and the
  klines still come from free `data.binance.vision`.
- `aimos/data/binance_symbols.py` exposes `all_binance_usdt_spot_symbols()` so
  both `download_history.py` and `run_backtest_card.py` share the same universe
  source without duplication.
- `scripts/run_backtest_card.py` now accepts `--all`, `--top-n`, and
  `--include-stable` so the same full-asset (or top-N) universe can be used for
  backtest run cards.

### Fixed (T-013 review follow-up)
- `aimos/backtest/engine.py` and `aimos/learning/dataset.py` length guards now
  require one extra bar (`+2`) so an empty replay/label pass raises a clear error
  instead of silently returning all-zero metrics.
- `scripts/train_from_history.py` catches `ValueError` from `build_training_set`
  per symbol, reports the skip, and continues with the remaining symbols.
- `specs/OPERATIONS.md` documents `learning.history.warmup` as `null` / resolved
  by `required_warmup(params)` rather than the old hard-coded 200.

### Added (T-013 — anti-lookahead warmup buffer)
- `aimos/observation/runner.py` exposes `required_warmup(params)`, the maximum
  `_min_bars()` advertised by all candle-based observation engines (currently
  driven by `correlation.beta_window`).
- `aimos/learning/dataset.py` and `aimos/backtest/engine.py` size their warmup
  buffers to `required_warmup()` and reject an explicit `warmup` shorter than the
  longest indicator lookback, preventing unstable indicator values from entering
  labels or trades.
- `config/default.yaml` sets `learning.history.warmup` to `null` so the default
  comes from the engine-derived minimum rather than the previous hard-coded 200.
- `tests/test_warmup_buffer.py` verifies buffer sizing, rejection of short
  warmups, exclusion of buffer bars from the label set, and walk-forward temporal
  separation.

### Added (T-001 — trade outcomes loop)
- `PaperBroker` now tracks per-position MAE/MFE in R units, builds an `OutcomeRecord`
  on close, and exposes `drain_outcomes()` for the runtime to persist.
- `BacktestEngine` drains outcomes into the journal after each tick.
- `PipelineOrchestrator.flush_broker_outcomes()` writes broker outcomes to the
  journal; journal write failures are logged and do not crash the loop.
- `aimos/runtime/paper_trader.py` and `aimos/runtime/serve.py` now flush broker
  outcomes after every `broker.step()`.
- `paper_trader.py` now uses `paper.journal_path` (default `state/aimos.sqlite`)
  instead of an in-memory journal so decisions and outcomes survive restarts.
- New test file `tests/test_outcomes_loop.py` covers TP/SL exits, short sign handling,
  MAE/MFE tracking, same-bar SL+TP precedence, hash-chain integrity, backtest/paper
  parity, zero-risk handling, and journal write failure resilience.

### Fixed (T-002 review follow-up — clock, staleness, per-pair skew)
- `live_venue_snapshot()`, `synthetic_venue_snapshot()` and `venue_snapshot_for()` now
  require an injected `Clock`; the `now` argument is retained for call-site
  compatibility but observation time comes from `clock.now()`. This removes the
  silent fallback that could stamp live quotes with stale bar-close time and fail
  the staleness gate.
- `CrossExchangeEngine._dislocation()` measures quote age against `clock.now()` instead
  of `ctx.now`, so `max_quote_age_seconds` actually rejects stale quotes in live runs.
- `compute_dislocation()` checks `max_venue_skew_seconds` per pair, not globally, so one
  slow exchange no longer blocks detection between the other contemporaneous venues.

### Fixed (cross-exchange arb phantom spreads — T-002)
- `compute_dislocation()` now consumes `VenueTop` bid/ask and computes the
  executable spread `bid[rich] - ask[cheap]` (after USD stable conversion)
  instead of `mid - mid`, eliminating phantom spreads.
- `live_venue_snapshot()` stamps each successful venue fetch with its own
  observation time; `CrossExchangeEngine` uses `max_quote_age_seconds` and
  `max_venue_skew_seconds` from `config/observation.yaml` to drop stale/skewed
  quotes before scoring.
- `serve.py` `_maybe_arb()` and `_price_row()` use the live `VenueTop` snapshot
  so prices reflect executable top-of-book.

### Added (finalized Kronos download spec — operator is fetching the weights now)
- Confirmed `specs/COMPETITIVE_ANALYSIS.md` already covers all 9 platforms from
  the shared document (7 table rows + Jesse + Gainium, added in an earlier pass
  this session) — no gap found on re-check.
- Operator is proceeding with Kronos Option B (real pretrained weights) now and
  deferring the 12-month history download; `specs/OPERATOR_ACTIONS.md` updated to
  reflect actual status per item rather than a fixed priority order.
- **`specs/KRONOS_INTEGRATION.md` §3.2 finalized** with a concrete, unambiguous
  spec rather than a sketch:
  - **Real measurement, not an estimate:** `pip download torch` from the default
    PyPI index produces a **526.6 MB** wheel (bundles CUDA support even for
    CPU-only use). The CPU-only wheel lives at `download.pytorch.org`, which is
    **also blocked from this session** (403) — a third host added to
    `specs/OPERATOR_ACTIONS.md`, alongside `huggingface.co` and
    `data.binance.vision`.
  - **Final variant recommendation: `Kronos-small` + `Kronos-Tokenizer-base`, not
    `Kronos-mini`**, with reasoning: once torch is loaded at all its own runtime
    overhead dwarfs the difference between an ~8 MB and an ~99 MB weight file, and
    Kronos-small's context length matches what upstream actually finetunes and
    evaluates with (`lookback=90`, confirmed via `finetune/config.py`, §2.0.2) —
    `Kronos-mini`'s extra 2048-token context buys nothing we'd use here.
  - Exact `huggingface-cli download` commands, exact `pyproject.toml` `[kronos]`
    optional-dependency group (isolated from the base/runtime/serve extras), the
    exact CPU-only install command, and an exact `vendor/manifest.yaml` stanza
    matching the existing `hb_mm`-entry style in that file.
  - Explicit about what's estimated (weight-file sizes computed from published
    param counts, torch CPU-wheel size and runtime RSS both unverifiable from this
    session) versus what's measured (the 526.6 MB CUDA wheel, confirmed by
    running the download) — step 5 now asks the operator to report measured RSS
    back, closing those gaps with real numbers instead of leaving them as guesses.

### Fixed (conflating this session's network limits with architectural decisions)
- The user pushed back directly: don't rule out a capability just because this
  development sandbox can't reach it — say so explicitly and hand off the exact
  command, since the operator's own machine, CI, or the production host is very
  likely unrestricted. Checking rather than asserting found this had actually
  happened, in two places:
  - `specs/KRONOS_INTEGRATION.md` §3 listed "weights are unreachable" as one of
    **four** reasons to reject using Kronos's real pretrained model — conflating
    a session-specific 403 with an architectural verdict. Verified directly:
    `curl https://huggingface.co` → `403`, but `pip install huggingface_hub`
    succeeds (PyPI isn't restricted) — the *package* is fine, only fetching from
    `huggingface.co` from this session is blocked. Rewrote §3 into an explicit
    **Option A (clean-room, still recommended) vs Option B (real weights,
    operator-provided)** split: §3.1 keeps the three reasons that hold regardless
    of who downloads the weights (dependency weight, CSI300-equities corpus
    mismatch, `torch.multinomial`'s lack of a seed contract), and new §3.2 gives
    the operator the exact `huggingface-cli download` commands, where to add the
    files (`vendor/kronos_weights/` + a `manifest.yaml` entry per the existing
    `vendor/VENDOR.md` pattern), and what still applies even with real weights in
    hand (out-of-process via KR-39, so torch never enters the trading process).
  - `specs/TASKS.md` T-003 step 1 (`scripts/download_history.py`) — verified
    `curl https://data.binance.vision` also returns `403` from this session.
    Added an explicit operator-action callout with the exact command; steps 2–4
    (integrity check, backtest, run card) have no network dependency and are
    unaffected.
- **New `specs/OPERATOR_ACTIONS.md`** — a single consolidated, living checklist
  of everything blocked by this session's network policy rather than by AIMOS
  itself, each entry showing the actual verified failure (not an assumption), the
  exact command to run, and what it unblocks. Two items currently: the 12-month
  history download (blocks T-003, the single highest-leverage task in the
  backlog) and the optional Kronos weights fetch. Explicitly states what is *not*
  on the list — GitHub, PyPI, and git are all reachable from this session — so the
  file stays a precise, narrow list rather than a hedge.
- **`CLAUDE.md`** — added a 5th item to the "before you start" checklist: check
  `specs/OPERATOR_ACTIONS.md` before concluding a capability is unreachable, and
  never fold a session-specific network restriction into an architectural
  decision without logging it there first. This is the fix meant to keep the
  mistake from recurring in a future session, not just this one.
- `specs/STATUS.md` now points at `specs/OPERATOR_ACTIONS.md` from the top of the
  file, so a stalled task is checked against "waiting on the operator" before
  being read as "not yet built."

### Fixed (STATUS.md drift after the Jesse/Gainium addition)
- `specs/STATUS.md` still said `specs/COMPETITIVE_ANALYSIS.md` covered "7 major
  OSS trading platforms" and "7 further tasks" after the Jesse/Gainium fix below
  landed — found while re-verifying cross-references between `STATUS.md`,
  `TASKS.md`, `KRONOS_INTEGRATION.md`, and `COMPETITIVE_ANALYSIS.md` in response
  to being asked whether everything was documented correctly. Corrected to 9
  platforms and 8 further tasks (T-007..T-009, T-012, T-014..T-017), with Jesse
  and Gainium named as MIT-licensed additions found only in the source
  document's prose, not its table. Also confirmed: every T-XXX cross-reference
  across the four spec documents resolves to a real, matching task — the only
  false positives were `KT-01..KT-63` (Kronos test-case IDs) substring-matching
  a naive `T-[0-9]+` grep.

### Fixed (competitive analysis coverage gap)
- The user asked "did we add everything we wanted to borrow from that document?"
  and checking rather than asserting found a real gap: `specs/COMPETITIVE_ANALYSIS.md`
  scoped itself to the source PDF's 7-row comparison table and missed **Jesse**
  and **Gainium**, both named only in the document's prose ("Jesse and Gainium
  cater to developers and no-code practitioners..."). Both verified and added as
  new §7a:
  - **Jesse** (`jesse-ai/jesse`) — **MIT**, fully borrowable. Its backtest
    decouples metrics from simulation (`jesse.services.report.portfolio_metrics()`,
    called once at run end) — this **confirms** `aimos/backtest/metrics.py`'s
    existing `compute_metrics()` design rather than changing it. Its one real
    contribution: Jesse documents "backtests without look-ahead bias" as a single
    named product guarantee. AIMOS has the same property (§9.1, KR-19, T-013) but
    stated across scattered spec text — folded into **T-013**'s acceptance
    criteria as a one-sentence guarantee with its own test suite, rather than a
    new task.
  - **Gainium** (`github.com/Gainium`, self-hosted Community Edition) — **MIT**
    across its self-hostable services. A no-code visual bot builder — wrong
    audience for AIMOS's config-and-code, single-operator model, so rejected. Its
    one structural note: paper-trading and connectivity run as separate deployable
    services rather than in-process modules — recorded inside **T-016** as
    precedent for *how far* to take paper/live isolation if that task ever
    concludes "yes," not as a push toward that conclusion.
  - Neither addition generated a new task ID — both sharpened existing tasks
    (T-013, T-016) rather than adding scope, which is itself worth recording: not
    every source in a document turns into new work, and saying so explicitly is
    part of an honest "did we cover everything" answer.

### Added (final audit reconciliation — closing the loop on "is everything documented")
- Went back through `PRODUCTION_READINESS_AUDIT.md` finding-by-finding against
  current code, rather than trusting the earlier backlog summary. One genuine gap:
  - **T-017 (new)** — audit **M6** (`/metrics` requires auth, breaking Prometheus
    scraping) is **still open in current code**: `_PROTECTED_EXACT = {"/metrics"}`
    in `aimos/api/server.py` still returns not-public, and `specs/OPERATIONS.md`
    has no Prometheus mention or documented resolution. Never closed, never
    explicitly accepted.
  - Confirmed **M2/M4 are moot**, not open — both lived in `aimos/saas/`, which no
    longer exists (`ls aimos/saas` → not found), deleted by the single-user refactor.
  - Confirmed **L3** (go-live gates markable out of order) is already fixed —
    `GoLiveLadder.mark()` rejects out-of-order completion per **REQ-8**, landed
    after the audit was written.
  - **T-006 escalated**: audit finding **L1** recorded this exact failure mode
    once already (STATUS claimed 465, measured 466) — the test count has now
    drifted at least twice. Cross-referenced with **L2** (`ta==0.11.0` fails to
    build against Debian-patched setuptools, reproduced independently while
    running this suite), which means the count is environment-dependent and a
    hardcoded figure in a "single source of truth" file will keep drifting.
    T-006 now asks for a computed count, not just a corrected one.

### Added (competitive analysis of 7 OSS trading platforms)
- **`specs/COMPETITIVE_ANALYSIS.md`** — review of QuantConnect LEAN, Hummingbot,
  NautilusTrader, Freqtrade/FreqAI, Abu, Passivbot, and OpenAlgo against AIMOS, with
  upstream file references and a licence verdict per platform.
  - **Licences verified at source, and the source document's licence column is wrong
    in 3 of 7 cases** — Abu is GPL-3.0 and OpenAlgo is **AGPL-3.0** (both listed only
    as "Open Source"), while Passivbot is Unlicense rather than MIT. Taking that
    column at face value would have added exactly the copyleft debt T-005 exists to
    retire. Borrowable: LEAN + Hummingbot (Apache 2.0), Passivbot (Unlicense).
    Concept-only: NautilusTrader (LGPL-3.0), Freqtrade, Abu (GPL-3.0). Avoid
    entirely: OpenAlgo (AGPL-3.0 network-use clause — AIMOS serves a dashboard).
  - **LEAN `Common/Statistics/TradeBuilder.cs` is a direct match for T-001** — it
    tracks `position.MinPrice`/`MaxPrice` via `SetMarketPrice()` and computes MAE/MFE
    at close, which is exactly the algorithm T-001 needs, under Apache 2.0. Also
    surfaces `EndTradeDrawdown` (profit given back before close) and `Duration`,
    neither of which AIMOS records.
  - Records where **AIMOS is already ahead** — trade-management barriers (our
    trailing stop carries a "never widens" invariant Hummingbot's does not),
    mechanically-enforced layering, hash-chained journal, fail-closed live path, and
    `NoTrade` as the default decision.
- **8 new tasks in `specs/TASKS.md`** from that review:
  - **T-013 (P0)** — anti-lookahead indicator-warmup buffer in train/test splits,
    from FreqAI's `buffer_timerange()`. Placed on the critical path **before T-003**:
    a warmup leak silently inflates every backtest number and is invisible unless
    specifically tested.
  - **T-007** Probabilistic Sharpe Ratio + Expectancy (LEAN `PortfolioStatistics.cs`)
    — PSR answers T-003's actual question, whether an edge is real or small-sample
    noise, which raw Sharpe cannot.
  - **T-008** power-law market-impact slippage (LEAN, Almgren et al. 2005) — our
    linear `slip_k` understates large-order cost; constants are equity-calibrated and
    need refitting for crypto.
  - **T-009** order-rejection retry state (Hummingbot `dca_executor.py`) — we handle
    unfilled orders but not exchange-rejected ones.
  - **T-012** `reduce_only` + OCO, **T-014** Dissimilarity-Index OOD confidence,
    **T-015** staged de-risking + peak-relative exposure cap, **T-016** paper/live
    state isolation.
  - Explicitly **rejected**: Passivbot's martingale grid (contrary to our risk
    model), Freqtrade strategy logic, and any event-bus rewrite for backtest parity.

### Added (coverage audit of the backlog itself)
- **`specs/TASKS.md`** gains the items a self-audit found missing:
  - **T-005 — GPL clean-room rewrite (audit PD3).** Verified this is the *only*
    production-readiness audit item still open: PD1 (network exposure) and PD5
    (RPO/RTO = 1 hour) are documented in `specs/OPERATIONS.md`, and PD2/PD4 were
    resolved by the single-user refactor (no `Organization` tables, no `maildrop`
    remain). Two freqtrade-derived GPL-3.0 files still require rewriting before any
    distribution; the tripwire exits 0 by design, so CI will never catch this.
  - **T-006 — test-count discrepancy.** `STATUS.md` claims 535 passed; a clean
    container run reproduces 493 with no skips or collection errors, and the gap
    does not close after installing the ML extras.
  - **Deferred section** — the 9 dormant features (D-01..D-09) and 5 not-built
    items (N-01..N-05) from `STATUS.md`, each with its gate, so nothing is silently
    dropped. Notes that **D-03 (ML fusion weight) and D-08 (IgnitionFade) both
    unblock from T-001**, and that N-02 must not start before T-002.
- **`specs/KRONOS_INTEGRATION.md` §2.0.2** — upstream's real training and inference
  settings from `finetune/config.py`, which differ materially from the demo the
  spec was first written against: they evaluate at **temperature 0.6** (not 1.0),
  `sample_count` 5, lookback **90** (not 400), and prediction length **10** (not
  120). KR-37's default is corrected to `temperature: 0.6` accordingly. Also
  confirms the finetune corpus is **CSI300 Chinese equities** (2011–2025) — a
  fixed-trading-hours market, which is exactly the calendar prior KR-6 drops for
  24/7 crypto — and records the full dependency weight (`torch>=2.0.0`,
  `huggingface_hub`, `safetensors`, `einops`), including that their
  `pandas==2.2.2` pin conflicts with ours at `2.2.3`.

### Added (backlog / requirements refinement)
- **`specs/TASKS.md`** — master tracked backlog (T-001..T-047) with a dependency
  graph, priorities, acceptance criteria, and explicit test cases per task.
  Records three P0 findings from a file-by-file review:
  - **T-001 — the measurement loop has never closed.** `Journal.write_outcome()`
    (`journal.py:101`) is fully implemented and hash-chained but is called by
    **zero production code**; the `outcomes` table is empty against 2,760 journaled
    decisions. `PaperBroker._close()` already computes 6 of 8 `OutcomeRecord`
    fields — only MAE/MFE tracking and one wiring call are missing. This starves
    ML labels, per-strategy attribution, analyst grounding, and drift detection.
  - **T-002 — cross-exchange arb computes phantom spreads.** `compute_dislocation()`
    compares mid-to-mid and discards `VenueTop.best_bid`/`best_ask`, overstating
    capture by ~one full spread; `live_venue_snapshot()` fetches venues
    sequentially then stamps them all with the same `now`, so no staleness gate is
    possible on that path.
  - **T-030..T-047 — 18 modules have no or weak test coverage**, including
    `intelligence/finalize.py`, `execution/base_plugin.py`, three enabled execution
    plugins, `observation/scalp_micro.py`, `runtime/atomic_io.py`, and the auth
    surface where the audit's two Criticals were found.
- **`specs/KRONOS_INTEGRATION.md`** refined:
  - §2.0.1 adds implementation-level architecture read from upstream `model/module.py`
    (BSQ straight-through estimator, commitment/entropy losses, bitwise s1/s2 split,
    cross-attention dependency layer, pre-norm RMSNorm + RoPE + SwiGLU) — enough to
    reimplement without reference to their code, and confirming KR-10 (numpy-only
    inference, no torch in the runtime) is realistic.
  - **KR-43 (new)** — the existing `bayes_engine.py` correlation guard keys on
    engine name, which a forecaster would evade while re-deriving what momentum and
    price action already report. Requires grouping by *information family* so
    double-counted information cannot inflate §6.7 meta-confidence, which gates
    trade eligibility. Corollary: `forecast_band` (forward range) is the genuinely
    new signal; `forecast_drift` is largely redundant.
  - §8 records **T-001 as a hard blocker** on the whole programme — K2's exit gate
    needs an information coefficient, which needs outcomes that do not exist.
  - §9 expands to a 60-case test matrix (KT-01..KT-63) mapped to the requirement
    each case defends.

### Added (research / requirements)
- **`specs/KRONOS_INTEGRATION.md`** — requirements spec for a K-line forecasting
  sensor, from a review of the Kronos foundation model (arXiv 2508.02739, MIT).
  Documents the one capability AIMOS lacks (a forward-looking *distributional*
  view of price), catalogues all twelve integration routes with binding verdicts,
  and specifies 42 numbered requirements (KR-1..KR-42) plus a K0–K5 rollout ladder.
  Decision: build an AIMOS-native clean-room implementation (BSQ-style hierarchical
  quantizer + ~1.2M-param causal transformer, numpy-only inference, ≈5 MB artifact)
  sized for a 4 GB CPU host — do **not** clone, vendor, or pip-install upstream, and
  do **not** add torch to the trading runtime. Enters strictly as a Layer-1
  `Evidence` sensor at reliability 0.35 behind `features.forecast_enabled`, on the
  same §8.3 promotion ladder that keeps `MLEngine` inert. No code, config, flag,
  dependency, or evidence name was added by this change.

### Added (Coolify / PaaS deployment)
- `aimos/runtime/serve.py` now reads `AIMOS_PORT` first, then `PORT` (the standard
  PaaS variable), while the bind address remains `AIMOS_HOST` only (default
  `127.0.0.1`) so a bare local run never accidentally binds a public interface.
- `Dockerfile` sets `PORT=8000` and `AIMOS_HOST=0.0.0.0` by default and adds a
  `HEALTHCHECK` against `/healthz` on the active port.
- `docker-compose.yml` and `run.sh` now use the `AIMOS_PORT` / `PORT` environment
  variable consistently, including the healthcheck and published port mapping.
- `README.md` and `specs/OPERATIONS.md` add a **Deploy on Coolify** section with the
  required env vars, persistent-storage paths, port/healthcheck notes, and first-run
  instructions.

### Added (live-trading prerequisites)
- **Test-connection endpoint** `POST /api/connections/test` runs a fresh read-only
  preflight for one venue using stored credentials and returns connected/can-trade/
  withdrawal-disabled/balance/error without echoing the key/secret.
- **Settings UI test button** on the Exchanges tab calls the new endpoint and shows
  a per-venue connection badge.

### Fixed (live-trading prerequisites)
- `preflight_check` now honors the stored `testnet` flag by calling
  `set_sandbox_mode(True)` for testnet keys; testnet credentials no longer fail
  against production endpoints.
- `SettingsStore` normalizes exchange venue and `exchange_id` to lowercase on
  write and lookup, so `Settings → Exchanges`, runtime preflight, the test
  endpoint, and the live broker all agree on the key.
- `POST /api/connections/test` validates the requested venue against the
  configured exchange list before invoking the exchange client, preventing
  arbitrary ccxt module access and outbound requests.
- `scripts/validate_integration.py` no longer treats a stored `testnet=false`
  key as an implicit `--mainnet` opt-in; the 5-second mainnet warning is now
  always required, and the preflight sandbox flag is aligned with `--mainnet`.

### Fixed (live-trading follow-up)
- `serve.py` now stores the read-only preflight result in `holder["connections"]`
  at boot so `GET /api/connections` and the `Connections` screen reflect the
  configured venues immediately instead of always reporting “No venue keys
  configured.”
- `scripts/validate_integration.py` imports `load_params_for_user` from the
  correct module (`aimos.settings.config`).
- `guard_live_boot` no longer refuses to start in paper mode when the mandate is
  enabled; it only gates boot when `mode=live` and the go-live ladder is not
  complete.
- `preflight_check` now sanitizes exchange error strings before returning them to
  the UI: URL query strings and `apiKey`/`secret`/`signature`/`sign` parameters are
  redacted so credential derivatives cannot leak through `error` payloads.

### Fixed (live-prereqs snapshot rehydration)
- `serve.py` now stores the per-venue `connections` map in the runtime snapshot
  view instead of the aggregated `{"venues": [...], "any_live": bool}` shape, and
  `_rehydrate_from_snapshot` converts the old aggregate back to a venue-keyed map.
  This prevents `GET /api/connections` and `GET /api/balances` from 500ing in the
  split API/loop process mode after the first state refresh.

### Changed (live-trading prerequisites)
- Runtime preflight (`_run_preflight`) and `scripts/validate_integration.py` now
  read exchange API keys from the encrypted `SettingsStore` first (the UI path),
  falling back to `AIMOS_SECRETS_FILE` / `AIMOS_KEY_<VENUE>` env vars for backward
  compatibility. This closes the split where keys added in Settings were invisible
  to the live/testnet path.
- The Connections screen and `validate_integration.py` messages now point operators
  to **Settings → Exchanges** as the primary key-management path.

### Changed (dashboard UI / shadcn)
- Replaced raw JSON dumps on Settings, Config, Models, and Controls with structured
  shadcn/ui forms, cards, switches, selects, and tables.
- Added a Tailwind v3 + shadcn/ui design system: `Button`, `Card`, `Input`,
  `Label`, `Switch`, `Select`, `Badge`, `Tabs`, `Table`, `Separator`, and a `cn()`
  utility. Preserved the old `Table(cols, rows)` and `Badge(dir)` APIs so existing
  screens keep working.
- Modernized the single-user login screen (`auth.jsx`) with the same card/input
  primitives and the dark theme.

### Fixed (dashboard UI / shadcn)
- Removed the invalid `--muted` CSS override so legacy `var(--muted)` consumers
  (`.b-flat`, `App.jsx`, `Prices.jsx`, `MindMap.jsx`, `Trades.jsx`) render grey
  text correctly.
- Defaulted `training` settings in `Settings.jsx` so the timeframe/months controls
  are always controlled and consistent with the CLI hint.
- Switched off/disabled feature badges to neutral `flat` in `Controls.jsx` and
  exchange metadata badges in `Settings.jsx` so expected-off states are no longer
  shown in destructive red.

### Changed (single-user mode)
- **Removed all SaaS/multi-tenant code**: the `aimos/saas` package, `config/saas.yaml`,
  the `saas` extra, and SaaS-specific tests/migrations are gone. AIMOS is now a
  single-user application.
- **Single-user auth from environment**: set `AIMOS_ADMIN_USERNAME` (default `admin`)
  and `AIMOS_ADMIN_PASSWORD` to log in. JWT secret is read from `AIMOS_JWT_SECRET`
  or generated and saved under `~/.aimos/secrets/.jwt_secret`.
- **New `aimos/auth` package**: `auth/security.py` handles JWT issue/validation;
  `auth/router.py` exposes `/auth/login`, `/auth/refresh`, `/auth/logout` and
  `/api/v2/me`.
- **New `aimos/settings` package**: `settings/settings_store.py` holds the
  encrypted config + exchange API-key store in the unified database
  (`user_settings` table) and `settings/config.py` merges user overrides into
  `Params` at boot.
- **`RuntimeStateStore`/`ControlStore` no longer have a SaaS backend**: only file
  and unified-database backends remain.
- **Dashboard auth simplified**: `auth.jsx` uses a single username/password step;
  the `Settings` screen no longer gates on SaaS and lets the single user manage
  mode, features, mandate, paper config, and encrypted exchange API keys.

### Fixed (single-user follow-up)
- Add a FastAPI exception handler for `AuthError` so `/auth/login` failures and
  missing/invalid tokens on `/api/v2/*` return **401** instead of 500.
- Remove the last active SaaS references in `dashboard/src/api.js` (comment +
  leftover `activeOrg`/`X-Organization-Id` header) and `specs/TESTNET.md`.
- Update `PRODUCTION_READINESS_AUDIT.md` and `specs/REQUIREMENTS_BACKLOG.md` with
  a single-user refactor note and replace the obsolete multi-tenant backlog.

### Added (unified operational database)
- **Single-PostgreSQL persistence option**: set `storage.database_url` (or
  `AIMOS__STORAGE__DATABASE_URL`) to one Postgres/SQLite URL and the journal,
  runtime state, controls, and model registry all live in that database. Existing
  file/SQLite backends remain the fallback when no URL is configured, so dev
  and tests are unchanged.
- **`aimos/storage/db.py`**: shared SQLAlchemy engine helper plus
  `runtime_states`, `runtime_controls`, and `model_registry` tables. URLs like
  `postgresql://` are normalized to the psycopg v3 dialect; `postgresql+psycopg://`
  is passed through.
- **Journal SQLAlchemy backend**: `Journal` now detects SQLAlchemy URLs and uses a
  per-organization schema on Postgres (`SET search_path`) while preserving the
  same `conn.execute(...)` interface and SHA-256 hash chain. File/SQLite backend
  is unchanged.
- **Runtime state + controls DB backend**: `RuntimeStateStore` and `ControlStore`
  accept an optional `database_url` and upsert JSON blobs per `organization_id`.
- **Model registry DB backend**: `ModelRegistry` accepts `database_url`/`org_id`;
  training runs append rows and promotion/demotion updates rows in the same DB.
- **TimescaleDB defaults to `storage.database_url`**: `TimescaleStore` now uses
  the unified DB URL when `storage.timescale_dsn` is empty (still no-op if it
  cannot connect).
- **Journal `is_writable()`**: abstracts the old SQLite `BEGIN IMMEDIATE`/`ROLLBACK`
  readiness check so `readyz` works identically for file and database journals.

### Fixed (unified operational database follow-up)
- Ensure `state/tenants/<org_id>` is created before the `RUNTIME_HALT` file is
  written so the emergency stop works when a database URL is configured.
- Removed implicit fallback to the SaaS auth DB; the SQL backend is only used
  when `storage.database_url` is explicitly set.
- Use `SET LOCAL search_path` for per-organization Postgres schemas so the
  setting does not leak across the shared connection pool to runtime state and
  model registry queries.
- Sanitize `org_id` to `[a-zA-Z0-9_-]` and truncate to 63 bytes before using it
  as a Postgres schema name.
- Allow keyword-style Postgres DSNs (`host=... dbname=...`) in `TimescaleStore`.
- Commit DML executed through the SQL journal connection adapter.
- Restore SaaS tenant-DB backend precedence in `ControlStore` and
  `RuntimeStateStore` so hosted deployments continue to share state when
  `storage.database_url` is not set.
- Make `_SqlJournal.close()` a no-op so it does not dispose the shared engine
  used by runtime state, controls, and the model registry.

### Added (REQ-13 — separate API process from trading loop)
- **Process modes via `AIMOS_PROCESS`**: `combined` (default, legacy), `api` (API-only),
  and `loop` (loop-only). `python -m aimos.runtime.serve` stays the default entrypoint;
  `python -m aimos.runtime.loop_process` runs the loop worker with no HTTP server.
- **Shared runtime state bus**: `RuntimeStateStore.save()`/`load()` now carry a
  serializable `view` (prices, candles, evidence, venue state, matrix, monitor,
  risk report, connections, tick) and `controls` (halt, pause, feature toggles).
  `OrganizationState` gained `view` and `controls` JSON columns with an Alembic
  migration so SaaS deployments share state in the tenant DB.
- **Cross-process control channel**: `ControlStore` writes/reads `control.json`
  (or `organization_states.controls`) so the API process can send operator
  commands (halt, pause, feature toggles) and the loop process applies them at
  the start of each tick.
- **API-only state rehydration**: `serve.py` builds the same runtime components,
  then a background loader refreshes `broker`/`sim`/`equity` and the `view` dict
  from the loop's snapshot every `paper.api_state_refresh_seconds` (default 1s).
  All API providers (`/api/markets`, `/api/prices`, `/api/candles`, `/api/trades`,
  `/api/positions`, `/api/balances`, `/api/monitor`, `/api/risk`, etc.) read the
  rehydrated objects, so the API process never needs the trading loop in memory.
- **Loop process isolation**: `AIMOS_PROCESS=loop` runs the paper loop + Telegram,
  monitor, stream, risk analytics, and journal backups without building the FastAPI
  app. The module-level `app` is `None` in loop mode to prevent accidental `uvicorn`
  use.

### Fixed (go-live verification blockers)
- **Killswitch reset gap closed**: added `POST /api/control/unhalt`, `PipelineOrchestrator.halt()` / `unhalt()` (persists/removes the `RUNTIME_HALT` file), and surfaced `halted` state in both `/api/features` and `/api/v2/status`. The dashboard **Controls** screen now shows a halt/reset panel and disables feature toggles while halted. Telegram killswitch falls back to the `halt()` method when available.
- **`/api/v2/status` now returns runtime feature flags and `halted`**: previously only returned `{"saas_enabled": true}`; now includes `features` and `halted` so public health/status clients see the same runtime state as `/api/features`.

### Removed / Changed (auth surface — operator decision on PD2)
- **Deleted the retired auth surface entirely** (resolves audit finding M1;
  operator's answer to PD2 for the auth-code half): `aimos/saas/oauth.py` and
  `aimos/saas/sms.py` removed; `register_email_password`, `verify_email`,
  `resend_email_verification`, `forgot_password`, `reset_password`,
  `login_email_password`, `send_phone_verification`, `verify_phone_and_login`,
  `login_with_google`, `login_with_apple`, and the dead `set_auth_cookies` removed
  from `aimos/saas/auth_service.py` / `router.py`. Removed the now-unused
  `UserIdentity`, `EmailVerificationCode`, `PasswordResetToken`,
  `PhoneVerificationCode` ORM models and the `oauth`/`sms` config blocks from
  `SaasConfig`. Dropped `Authlib` from `pyproject.toml`.
- **The only login flow is now email + password + email OTP** — no phone/SMS
  login, no Google/Apple OAuth, no self-service password reset. Nothing dormant
  remains to audit or accidentally re-expose. `admin.phone` is kept as an
  informational profile field only (returned by `/api/v2/me`), not a login path.
  Verified: all 26 `test_saas.py` tests pass unchanged (the surface was fully
  dead — zero test coverage of it existed), and a live end-to-end login
  (password → OTP → token) still works after the removal.
- **Documented [Brevo](https://www.brevo.com) as the recommended SMTP provider**
  for the login OTP (`config/saas.yaml`, `specs/OPERATIONS.md`) — free-tier SMTP
  relay, no code change since `email.py` already speaks plain SMTP.
- Corrected a stale `specs/STATUS.md` line: runtime state (equity/balances/
  broker/sim/ladder) already persists across restarts via `RuntimeStateStore`
  (wired into `serve.py`'s boot/save loop) — it was listed as not-built.
- **New `specs/REQUIREMENTS_BACKLOG.md`** — 19 prioritized requirements
  consolidating the production-readiness audit's residual items (M2–M9, PD1/PD3/
  PD5, Group 3/4 remediation items) with a competitive-feature review against
  TradingAgents (Tauric Research) and the OpenBB Platform. Notably: REQ-1 (wire
  the already-built, already-tested `risk/analytics.py` alpha/beta/VaR-ES to an
  API endpoint and the dashboard — currently unreachable) and REQ-11 (formalize a
  no-copyleft-in-`aimos/` dependency policy, since OpenBB is AGPLv3 and the
  network-use clause would apply if it were ever imported directly).

### Security / Fixed (audit remediation)
- **C1 (Critical) — SPA path traversal closed.** `runtime/serve.py` now resolves the
  requested path and serves a file only when it is inside `dashboard/dist`
  (`is_relative_to`), else returns the SPA shell. Verified live: `…/state/.jwt_secret`,
  `…/config/mandate.yaml`, `…/CLAUDE.md` all return the shell, not the file.
- **C2 (Critical) — dashboard reachable with auth on.** `api/server.py` middleware
  exemption rewritten (`_is_public_path`): the SPA shell + `/assets/*` are public,
  `/api/*` and `/metrics` stay token-gated. Verified live + login page renders in a
  browser under SaaS.
- **H1 — control API hardened.** Default `AIMOS_HOST` is now `127.0.0.1`; control and
  assistant endpoints refuse non-loopback callers when SaaS is off.
- **H2 — OTP no longer leaked.** The no-SMTP log no longer includes the email body;
  `state/maildrop` / `state/smsdrop` are opt-in via `AIMOS_DEV_MAILDROP` and written
  `0600`. Fixed a `NameError` in `_render_password_reset_email`.
- **H3 — auth brute force bounded.** Login codes are burned after 5 wrong guesses
  (`EmailLoginCode.attempts`); `/auth/*` is rate-limited per client (429).
- **M8 — atomic state writes.** New `runtime/atomic_io.py` (temp + fsync + rename);
  `state_store.load` tolerates a torn file; `golive` keeps a `.bak` and restores it.
- **H4 — journal backups.** New `scripts/backup_journal.py` — SQLite online-backup
  API (consistent under writes) + immediate hash-chain verify + retention + an
  atomic `journal-latest.sqlite` pointer. `scripts/restore_drill.sh` now **exits 1**
  when no backup exists (a drill with no backup is not a pass).
- **H5 — CI.** New `.github/workflows/ci.yml` runs pytest + all three lints + the
  GPL tripwire + a backup/restore drill, plus a dashboard-build job, on every
  push/PR so the gates are enforced rather than discipline-only.
- **L5 — accessibility.** `dashboard/index.html` sets `<html lang="en">`.
- Suite grew 466 → **514 passed / 1 xfailed**; magic-number, naive-datetime, and
  import-linter (6/6) gates remain green. **All Critical/High/Medium audit blockers
  are now fixed**; recommendation moves to **STOP — CONDITIONAL GO** (conditional on
  an independent verification pass + product decisions PD1–PD5).

### Added
- **REQ-1 — wired `aimos/risk/analytics.py` to a live endpoint and the dashboard.**
  New `aimos/risk/analytics_runner.py` fetches BTC + equal-weight T1-basket returns,
  aligns them with the equity curve, and computes VaR/ES (95%/99%), alpha/beta + t-stat
  vs both benchmarks, and the BTC-beta / idiosyncratic factor split. A daily
  APScheduler job in `runtime/serve.py` caches the report; `GET /api/risk` serves it
  (and computes on demand when empty). `PositionsRisk.jsx` renders the stress panel
  and `Performance.jsx` shows alpha/beta attribution. Config added to `config/default.yaml`
  (`risk.enabled`, `interval_seconds`, `timeframe`, `min_samples`); tests in
  `tests/test_risk_analytics_api.py`.
- **Fixed `dashboard/src/components/EquityChart.jsx` for `lightweight-charts` v5.**
  Replaced the removed `chart.addLineSeries()` with `chart.addSeries(LineSeries, {...})`
  so the **Performance** screen mounts and the new alpha/beta tiles are reachable.
- **REQ-3 — bound `/api/decisions?limit=` to [1, 500].** Added `Query(..., ge=1, le=500)`
  in `aimos/api/server.py` and the same clamp to `_assistant_decisions` in
  `aimos/runtime/serve.py`; added `tests/test_decisions_limit.py`.
- **REQ-6 — public `/healthz` and `/readyz` endpoints.** `/healthz` returns 200 when the
  process responds; `/readyz` returns 200 only when the journal is writable and the
  paper-loop heartbeat is fresher than `health.heartbeat_stale_seconds` (default 30 s).
  Wired into `docker-compose.yml` as the `aimos` service healthcheck.
- **REQ-8 — sequential go-live gate sign-off.** `GoLiveLadder.mark()` now rejects
  out-of-order gate completion; `unmark()` removes the target gate and all subsequent
  gates. `tests/test_golive.py` covers both behaviors.
- **REQ-11 — copyleft dependency policy.** Added a standing hard rule: no GPL/AGPL
  package is imported into `aimos/`; wanted capabilities run as isolated out-of-process
  services. `scripts/check_gpl_tripwire.py` now also scans `pyproject.toml` dependency
  pins for copyleft packages (OpenBB, etc.).
- **REQ-18 — dummy bcrypt comparison on login not-found path.** `send_login_otp()`
  now runs `verify_password(password, DUMMY_PASSWORD_HASH)` before raising, so an
  unknown email is indistinguishable from a wrong password by timing.
- **REQ-4 — admin password change endpoint and UI.** `POST /api/v2/me/password`
  verifies the current password, enforces `is_strong_password`, updates the admin
  hash, and revokes all outstanding refresh tokens. `ensure_admin_user()` no longer
  re-hashes the existing admin password on every boot, so config edits cannot
  silently revert an out-of-band password change. Settings screen includes a
  "Change admin password" form.
- **REQ-5 — auth audit log and fatal admin-seed failures.** `aimos/saas/db.py`
  now logs and re-raises admin-seed failures when SaaS is enabled. A new
  `AuthAuditLog` table records structured auth lifecycle events (login attempt,
  OTP verify, refresh, logout, exchange-key add/remove, password change) with
  email/user_id, success, client IP, user agent, and detail.
- **REQ-7 — Telegram alert on repeated failed logins.** `FailedLoginTracker`
  counts failed `/auth/login` and `/auth/login/verify` attempts per email and
  IP; when the configured threshold is crossed, it calls the Telegram sink's
  `send()` so the operator is alerted to brute-force attempts. Configurable via
  `saas.failed_login_alert_threshold` and `failed_login_alert_window_seconds`.
- **REQ-17 — httpOnly refresh-token cookie + CSP headers.** The refresh token
  is no longer returned in JSON; `/auth/login/verify` and `/auth/refresh` set it
  as an `httpOnly; Secure (HTTPS); SameSite=Strict` cookie and `/auth/logout`
  clears it. The access token stays in memory only (no `localStorage`), and the
  dashboard loads a session on boot by silently calling `/auth/refresh`. A
  default `Content-Security-Policy` plus `X-Frame-Options: DENY` and
  `X-Content-Type-Options: nosniff` is added to every response.
- **REQ-19 — AI analyst case-for/case-against narrative.** New `GET
  /api/assistant/debate/{decision_id}` returns a two-sided post-hoc explanation
  for a completed decision, grounded in the decision graph + journal/metrics
  evidence and clearly labeled as read-only, post-hoc commentary.
- **REQ-9 — Alembic migrations for the SaaS/auth DB.** Replaced
  `Base.metadata.create_all` with Alembic `upgrade head` in
  `aimos.saas.db.run_migrations()` and `scripts/migrate_to_saas.py`.
  Added `alembic/` environment wired to `aimos.saas.models` + `settings_store`,
  a baseline migration (`001`) creating all auth/tenant/settings tables, and
  `002` adding the `EmailLoginCode.attempts` brute-force counter. `alembic` is
  added to the `saas` extra in `pyproject.toml`.
- **REQ-10 / PD1 — network-exposure model decision.** Default deployment is
  loopback-only; external reach requires an authenticated reverse proxy/VPN or
  SaaS-enabled token auth. Documented in `specs/OPERATIONS.md`; H1 loopback-gate
  behavior is unchanged.
- **REQ-12 / PD5 — scheduled journal backups.** Refactored
  `scripts/backup_journal.py` into `aimos/journal/backup.py` so the runtime can
  call `backup_journal` directly. Added `backup` config (`config/default.yaml`)
  with default `interval_seconds: 3600` (RPO = 1 hour) and `keep: 14`.
  `aimos/runtime/serve.py` registers an APScheduler `journal_backup` job using
  the per-tenant journal path. `specs/OPERATIONS.md` records the default RPO/RTO.
- **REQ-14 — move key material outside the working directory.** JWT and settings
  Fernet keys now default to `~/.aimos/secrets` (overridable via `AIMOS_SECRETS_DIR`).
  `docker-compose.yml` mounts a separate `secrets` volume at `/app/secrets` so
  key material is outside `dashboard/dist`'s ancestry even when the runtime is
  deployed in a container.
- **REQ-16 — real `OnchainProvider` for the dormant on-chain engine.** Added
  `CoinMetricsCommunityProvider` that fetches `AdrActCnt` for the base asset and
  `FlowInAllNtv` for a configurable stablecoin asset, with no API key required.
  `config/observation.yaml` gains `onchain.enabled`/`provider`/`api_key` knobs and
  `aimos/observation/runner.py` wires the provider into `OnchainEngine` at build
  time.
- **REQ-15 — dashboard accessibility pass.** Added global `:focus-visible` outline
  and `prefers-reduced-motion` support in `dashboard/src/index.css`; labeled the
  `DecisionAnatomy` and `Assistant` controls that were missing programmatic
  labels. All 21 screens remain keyboard/screen-reader navigable.
- **`PRODUCTION_READINESS_AUDIT.md`** — end-to-end product and production-readiness
  audit at commit `5fd1b88`. Audit-only; **no application source was modified**.
  18 findings (2 Critical, 5 High, 7 Medium, 4 Low); recommendation **CONTINUE — NO-GO**.
  Baseline recorded: 466 passed / 1 xfailed, magic-number + naive-datetime lints
  clean, import-linter 6/6, GPL tripwire armed (2 files).
  - **C1 (Critical)** — unauthenticated path traversal in the SPA catch-all
    (`runtime/serve.py:892`): percent-encoded `../` escapes `dashboard/dist` and
    serves `state/.jwt_secret`, `state/.settings_key`, `state/maildrop/*`,
    `secrets.yaml`, `.env`, `/etc/passwd`. Reproduced by execution.
  - **C2 (Critical)** — enabling `saas_enabled` makes the dashboard, its login page,
    and `/assets/*` return 401 (`api/server.py:111` exemption list omits non-API
    paths), so auth cannot be switched on. Reproduced by execution.
  - **H1** — control API (killswitch, feature toggles, go-live sign-off, LLM
    assistant) is unauthenticated when `saas_enabled` is false (the default).
  - **H2** — login OTPs logged at WARNING and written unconditionally to
    `state/maildrop/` in plaintext, violating the "secrets are never logged" rule.
  - **H3** — no inbound rate limiting or lockout; OTP codes are not invalidated on
    failed attempts; 275 ms of bcrypt per unauthenticated request is a DoS vector
    against the process that also runs the trading loop.
  - **H4** — no backup mechanism exists and `scripts/restore_drill.sh` exits 0 when
    no backup is found.
  - **H5** — no CI/CD; the four documented quality gates are unenforced.
  - **Pass 2 (live-server execution):** built the dashboard and ran the real app.
    C1 confirmed against the running server and the full kill chain proven
    (traversal → leak `state/.jwt_secret` → forge a token that `decode_token`
    accepts as admin). Dashboard renders (21 screens, 0 console errors); no XSS
    sink exists; the Telegram channel verified as a genuine strength. Added **M8**
    (non-atomic `state.json`/`go_live.json` writes — torn write crashes boot or
    silently wipes go-live sign-offs, both reproduced) and **L5** (`<html>` missing
    `lang`). **No new Critical/High** — recommendation unchanged at **NO-GO**.

### Changed
- **Single-admin mode + email OTP 2FA** (`aimos/saas/`):
  - Removed public registration, Google/Apple OAuth, phone OTP, and forgot-password
    endpoints; the only auth flow is admin login.
  - Admin credentials (user_id, email, phone, password) are seeded from
    `config/saas.yaml` `admin.*` or `AIMOS__SAAS__ADMIN__*` env vars and hashed on
    first run.
  - Login is two-step: `/auth/login` verifies the password and sends a one-time
    code to the admin email; `/auth/login/verify` validates the code and issues
    JWT access/refresh tokens.
  - Dashboard `auth.jsx` and `api.js` updated for the new flow.

### Docs
- Updated `README.md`, `specs/OPERATIONS.md`, `specs/DEPLOYMENT.md`,
  `specs/STATUS.md`, `.env.example`, `.env.prod.example`, and
  `specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md` to describe the
  single-admin auth model, email OTP 2FA, encrypted `SettingsStore`, and the
  `/api/v2/settings` control plane. Removed references to the retired
  multi-user/multi-tenant SaaS design.

### Added
- **SaaS v2.0 Phase 1 auth foundation** (`aimos/saas/`): SQLAlchemy user/org models,
  bcrypt password hashing, JWT access/refresh tokens with rotation, email
  verification and password reset over SMTP, phone OTP with console/Twilio/Vonage
  pluggable sender, Google + Apple OAuth2 helpers, and `/auth/*` + `/api/v2/*`
  FastAPI routers. Config-driven via `config/saas.yaml` and `AIMOS__SAAS__*`
  env overrides; master switch `features.saas_enabled` (default `false`) keeps the
  single-user path unchanged.
- **Dashboard auth screens and tenant-aware API client** (`dashboard/src/auth.jsx`,
  `dashboard/src/api.js`, `dashboard/src/App.jsx`): login/register/email-verification,
  organization switcher, per-tenant `X-Organization-Id` header, and an
  `/api/v2/status` probe so the dashboard falls back to local mode when SaaS is
  disabled. `npm run build` is green.
- **SaaS v2.0 Phase 2 runtime state + per-tenant journal scaffolding**:
  - `aimos/runtime/state_store.py` persists equity curve, broker state, multi-venue
    balances, positions, go-live ladder, and feature flags across restarts. Saves
    beside the journal for isolated deployments; uses the tenant DB when SaaS is on.
  - `aimos/saas/journal_tenant.py` routes each organization to its own journal.
  - `aimos/saas/state_tenant.py` persists per-tenant runtime state in the auth DB.
  - `PaperBroker` and `MultiVenueSim` gain `state_dict()` / `load_state()` so the
    paper loop can resume after a restart.
  - `runtime/serve.py` loads state at boot and snapshots it every tick.
- **Dashboard charting + screens**:
  - `dashboard/src/components/EquityChart.jsx` — `lightweight-charts` line chart
    on the Performance screen, driven by `/api/equity`.
  - `dashboard/src/components/CandlestickChart.jsx` + `dashboard/src/screens/Candles.jsx`
    — OHLC candlestick chart with per-venue selector, driven by the new
    `/api/candles/{symbol}` endpoint.
  - Evidence tables remain on `Engines`, decision anatomy flow on `DecisionAnatomy`,
    and the new `Settings` screen handles members/invites.
- **Dashboard auth screens completed** (`dashboard/src/auth.jsx`):
  login, registration, email verification, forgot-password/reset, and phone-OTP
  sign-in are now wired to the SaaS auth endpoints.
- **Dashboard settings / organization screen** (`dashboard/src/screens/Settings.jsx`):
  lists organization members, sends invites by email/role, and displays per-tenant
  config overrides. Routes and API helpers added to `App.jsx` and `api.js`.
- **Tenant members + invite tests** (`tests/test_saas.py`):
  covers `GET /api/v2/organizations/{id}/members` and `POST .../invite`.
- **Test coverage for v2.0 modules`:
  - `tests/test_runtime_state.py` — roundtrip save/load of equity, broker, and
    multi-venue balances.
  - `tests/test_model_registry.py` — registry append, promote, demote, drift.
  - `tests/test_streaming.py` — `StreamRecorder` JSONL output and Binance trade
    normalization.
  - `tests/test_migrate_to_saas.py` — single-user → tenant migration.
  - `tests/test_download_history.py` — ZIP CSV parsing and timeframe helpers.
  - `tests/test_vendor.py` — manifest validity, vendoring script dry-run, vendor
    module importability, GPL tripwire presence, and the runtime-import ban on
    `vendor.vt_research`.
  - `tests/test_live_multi_venue_wiring.py` — fail-closed live-router construction
    (no keys, incomplete ladder, missing credentials) and `_maybe_arb` routing
    with mock `LiveBroker` legs + unwind detection.
- **ML model registry + promotion/demotion hooks** (`aimos/learning/registry.py`):
  `scripts/train_from_history` now records every run (AUC, Brier, status) to
  `state/model_registry.json`, checks Brier degradation for auto-demotion, and
  prints the exact config lines to enable the model in shadow only after the AUC
  gate passes. The ML fusion weight stays fail-closed at 0 until a human raises it.
- **12-month historical dataset downloader** (`scripts/download_history.py`):
  free public Binance Vision monthly klines → `CandleStore` parquet for ML
  training and regression tests. Supports multi-symbol and `1m/5m/15m/1h/4h/1d`.
- **Per-tenant config overlay + runtime tenant context** (`aimos/saas/config_tenant.py`):
  deep-merges organization-specific overrides from `OrganizationConfig` into the
  base `Params` tree at runtime; `runtime/serve.py` now boots with
  `load_params_for_org(AIMOS_RUNTIME_ORG_ID)` and routes journal/state to the
  per-tenant paths.
- **SaaS org-scoping middleware** (`aimos/api/server.py`):
  trading endpoints (`/api/*` outside `/api/v2/*`) require a valid access
  token whose `org` claim matches `X-Organization-Id` and `AIMOS_RUNTIME_ORG_ID`
  when SaaS is enabled; tenant routes still use `TenantContext`.
- **Vendor vendoring scaffolding** (`scripts/vendor.py`, `vendor/manifest.yaml`):
  reproducible vendoring at pinned SHAs for all six `vendor/` packages with a
  `--dry-run` / `--apply` workflow; `vendor/VENDOR.md` is updated with the pinned
  SHAs and notes which packages still need exact-path / import-rewrite review.
- **Live multi-venue executor wiring** (`runtime/serve.py`):
  `_build_live_router` constructs a `MultiVenueLiveRouter` only when every gate is
  open (`features.multi_venue_live`, `mode=live` or `mandate.enabled`, a complete
  go-live ladder, and per-venue API keys from the secrets file). `_maybe_arb` now
  routes cross-venue arbs through live brokers when the router is present, otherwise
  it stays on the paper simulator. No keys are required or enabled by default.
- **Candlestick API** (`/api/candles/{symbol}`):
  `runtime/serve.py` stores per-venue OHLC DataFrames each tick and exposes them
  as `{time, open, high, low, close}` candle arrays for the dashboard chart.
- **Deployment packaging for SaaS**:
  - `Dockerfile` multi-stage build (Node dashboard + Python runtime) installing
    `[serve,saas,data]` extras; `docker-compose.yml` now passes the shared
    Postgres DSN to `AIMOS__SAAS__DATABASE_URL` so the tenant/auth DB can run
    on the same TimescaleDB container.
  - `scripts/migrate_to_saas.py` migrates an existing single-user deployment to
    a default tenant (`local`), copies `state/aimos.sqlite` to the per-tenant
    journal path, and optionally creates an owner user.
- **Streaming layer** (`aimos/data/streaming.py`, `aimos/data/stream_feed.py`):
  - `BinanceWebsocketSource` connects to Binance combined websocket streams
    (`@trade`, `@depth`, `@miniTicker`) and normalizes events into a venue-agnostic
    `StreamEvent` shape.
  - `StreamRecorder` writes events to `state/streams/<date>.jsonl` for
    deterministic replay via `RecordedStreamSource`.
  - `StreamFeed` converts live `@depth` and `@trade` events into `BookAggregate`
    and `LargePrint` objects and injects them into the slow paper loop's
    `MarketContext` when `features.streaming_enabled` is true.
  - Configurable via the new `streaming` section in `config/default.yaml`.
- **SaaS v2.0 requirements and task tracker** (`specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md`):
  roadmap for finishing the remaining runtime pieces (streaming, persistence, dashboard
  charting, ML pipeline, vendor vendoring, 12-month dataset, live multi-venue wiring)
  and adding a self-hostable SaaS layer with Google/Apple/email/phone auth and
  multi-tenant organizations. Designed to use only free/open-source dependencies and
  operator-supplied credentials; no paid third-party services required.
- **OpenAI backend for the AI analyst** — the analyst now supports `assistant.provider:
  openai` (default `gpt-4o-mini`, cheap) alongside Anthropic, selected by config; same
  grounded, read-only prompt, injectable caller (both covered by offline tests). Uses
  `OPENAI_API_KEY`. Config gains `assistant.provider` + `assistant.openai_model`.
- **`specs/DEPLOYMENT.md`** — one end-to-end runbook: run → paper (for months) →
  Telegram → AI analyst (Anthropic/OpenAI) → deploy cheaply (~$5/mo VPS + Docker
  Compose) → testnet validation → train/enable ML → **when and how to go live**
  (the fail-closed ladder + a go/no-go checklist) → emergency stop. Linked from the
  README; `.env.example` gains `OPENAI_API_KEY` + analyst env vars.
- **Read-only AI analyst** (`aimos/runtime/assistant.py`, `specs/ASSISTANT.md`):
  a natural-language assistant — dashboard **AI Analyst** chat screen + Telegram
  `/ask` and `/report` — that answers questions about the running system and
  generates timeframe reports **grounded in the journal + real metrics** (recent
  decisions, performance, ML/model status, monitor coverage, features, go-live,
  equity). It is the sanctioned LLM role (§15.3): strictly read-only, it explains
  and *advises* but cannot trade, flip flags, or edit config — any action it
  recommends goes through the existing CONFIRM-gated controls. The LLM caller is
  injected (plain httpx to the Anthropic Messages API), so grounding/prompting is
  fully tested offline. Off by default (`assistant.enabled` + `ANTHROPIC_API_KEY`),
  on-demand only (never per tick); secrets never enter the prompt.
- **Train the ML on older data via paper replay** (`aimos/learning/dataset.py`,
  `scripts/train_from_history.py`): replays historical candles (Binance-vision CSVs,
  the parquet CandleStore, or offline synthetic) through the exact production
  observation→intelligence pipeline (anti-lookahead), labels every decision with the
  triple-barrier method, and trains a walk-forward-validated logistic model. Feature
  construction is unified with inference via the new `IntelligenceLayer.ml_feature_vector`
  (single source of truth → no train/serve skew). **Enable/disable switch:** off by
  default (`learning.history.enabled`); the trained model is saved in **shadow**
  (fusion weight 0) and the script prints the exact one-line change to enable it —
  and only if it clears the AUC gate. Nothing reaches the decision path until a human
  raises `intelligence.fusion_weights.ml` after the shadow window (§8.3).

### Fixed
- **Decision-path edge cases** found in end-to-end adversarial testing (new
  `tests/test_decision_edge_cases.py`, arb invariant test):
  - **Sizer no longer emits a zero-notional "trade."** An asset already at its
    concentration cap drove the risk-based size to 0, which passed every gate
    (default `min_notional=0`) as a `LONG size_quote=0.0`. The sizer now rejects a
    non-positive or non-finite final size before it reaches the risk manager/broker.
  - **Non-finite geometry can't reach an order.** A NaN/inf price propagated all the
    way to `size_quote=NaN`; the sizer now rejects non-finite entry/stop, and
    `TrendFollowing` no longer emits a plan from a non-finite/≤0 price.
  - **Evaluator drops stop-less / non-finite-EV candidates.** A candidate with no
    usable stop distance had its costs ignored and could win — then get rejected at
    sizing, suppressing a valid trade. Such candidates are now dropped up front.
  - **Multi-venue arb can't drive a venue negative.** The inventory constraint now
    includes the buy-side fee, so a venue never spends USDT it doesn't hold (was
    going negative by the fee amount); total USDT stays conserved.

### Added
- **Feature monitor agent** (`aimos/runtime/monitor_agent.py`): a background self-
  tester that probes every feature on an interval (universe, per-venue prices &
  decisions, engines, cross_exchange, scalp, trades, balances, performance, mind-
  map, connections, go-live) and publishes a coverage report — ok/degraded/failing
  + coverage % — to `/api/monitor`, `state/monitor_report.json`, and a new
  **Monitor** dashboard screen. With `monitor.force_coverage` it flips the safe
  keyless flags (cross_exchange, scalp) on once so every path is exercised without
  waiting for organic conditions — fast, hands-off testing. Never touches
  live/funded features. Off by default (`monitor.enabled`); wired into `serve`.
- **`specs/TESTNET.md`**: step-by-step guide to get free Binance **testnet** keys
  (GitHub SSO, fake funds, real API), wire them via `AIMOS_SECRETS_FILE`/env, arm a
  tiny mandate, and run the live-integration validator — the safe way to prove the
  live path works before risking money, plus the mainnet path and troubleshooting.
- **Live-integration validator** (`aimos/runtime/validate.py`,
  `scripts/validate_integration.py`): runs the real account+order path against an
  exchange **testnet** (free, real API) — authenticate → balance → withdrawals-
  disabled → place tiny order → cancel → reconcile — and prints a PASS/FAIL report,
  marking the go-live testnet gate on all-pass. The safe way to confirm the build
  works against a real exchange before risking money. Mock-tested.

### Fixed
- **`.env` templates**: removed a stale, misleading `BINANCE_API_KEY`/`BINANCE_SECRET`
  block (the code reads `AIMOS_KEY_<VENUE>` / a secrets file, not those names).
  Clarified the exchange-key section and listed all three venues
  (binance / kraken / coinbase) in `.env.example` and `.env.prod.example`.

### Added
- **TimescaleDB time-series store** (`aimos/storage/timescale.py`, optional): writes
  equity / decisions / prices / trades to hypertables when `AIMOS_TIMESCALE_DSN`
  is set and `psycopg` is installed (`pip install '.[timescale]'`); safe no-op
  otherwise. Wired into the serve loop; `docker-compose` points it at the
  TimescaleDB service. The SQLite hash-chained journal stays the system of record.
- **Persistent journal by default**: `paper.journal_path` now defaults to
  `state/aimos.sqlite` (was in-memory).
- **Docs reorganized**: consolidated Markdown into `specs/` (ARCHITECTURE, MODELS,
  OPERATIONS, STATUS); new root `README.md`, this `CHANGELOG.md`, `CLAUDE.md`, and
  Cursor rules that require reading `specs/STATUS.md` + this changelog first.

### History (chronological)
- **Hard boot guard** — the app refuses to start in `mode: live` (or with the
  mandate enabled) until every go-live gate is signed off (`guard_live_boot`).
- **Go-live ladder tracker** — the six §23.8 gates as a checklist with UI progress
  (`/golive`), CONFIRM-gated operator sign-off, a testnet order probe
  (`scripts/testnet_order.py`), and `GO_LIVE.md` runbook.
- **Runtime feature toggles** (UI Controls screen + Telegram `/features`, `/enable`,
  `/disable`) for the safe keyless flags (scalp, cross_exchange); live/funded flags
  are LOCKED and refuse to flip.
- **Phase D** — gated live multi-venue executor (`LiveBroker` + `MultiVenueLiveRouter`,
  mandate + withdrawal gated, mock-tested), read-only key **preflight self-check**
  + Connections panel, secret loading (file + env), real balance UI; **scalp enabled**
  (MomentumScalp + proxy micro-engine).
- **Phase C** — decision **mind-map** (`/mindmap`): evidence → fusion → regime →
  strategies → chosen as a node graph.
- **Phase B** — **simulated multi-venue arb execution** (two-leg buy-cheap/sell-rich,
  inventory-constrained), **Trade History**, **Balances**, real **Performance**.
- **Phase A** — full **per-venue analysis** across binance/kraken/coinbase +
  **multi-platform price matrix** + per-venue Engines.
- **One deployable server** — `aimos.runtime.serve` = dashboard + paper loop +
  Telegram, auto-started; persistent journal option.
- **Universe wired into the runtime** — top-N by volume (discovery + seed fallback),
  refresh, cross-venue-biased selection; live-polling UI; Engines/Strategies/Models
  screens.
- **Cross-exchange arbitrage (P8)** plugin + multi-venue data; fixed `.gitignore`
  that had been excluding the whole `aimos/data/` package.
- **Runnable paper mode** — feature flags, `.env` templates, end-to-end paper loop,
  working React dashboard, `./run.sh` one-command full stack; stubs replaced with
  real implementations.
- **Phases 0–6** (original build contract): contracts → data infra → universe
  manager → 13 observation engines → intelligence (rule/bayes/fusion) → execution/
  journal/backtester → runtime/UI/telegram/ignition/risk-analytics → learning/
  agents/LLM-sensor/live-broker/go-live-gates. §25.9 golden path reproduces exactly.

See `git log` for commit-level detail and `specs/STATUS.md` for the current
build state and what's still dormant.
