# KRONOS_INTEGRATION — requirements for a K-line forecasting sensor

**Status:** requirements only. Nothing in this document is built. No code, config,
flag, dependency, or evidence name has been added to AIMOS by this document.

**Scope decision (locked):** we do **not** clone, vendor, or import
`shiyu-coder/Kronos`. We build an AIMOS-native capability that reproduces the
*ideas* that make Kronos useful, sized for a **4 GB RAM CPU-only host**, wired in
as a Layer-1 **sensor** that emits `Evidence` — never as a signal, never in the
decision path, never touching the live-order path.

---

## 1. Executive summary

| Question | Answer |
|---|---|
| Are we missing something valuable? | **Yes, one thing:** AIMOS has no *forward-looking, distributional* view of price. Every one of the 13 observation engines is backward-looking and point-valued. |
| Should we adopt Kronos itself? | **No.** Adopt the *concepts*. See §3 for why. |
| Can it fit without disrupting the app? | **Yes**, on exactly one route: a new observation engine emitting registered `Evidence`. Every other route breaks a hard rule (§4). |
| Cost to the runtime | ~1.2M params, ≈5 MB weights, target < 350 MB added RSS, ≤ 50 ms p95 per symbol·timeframe. Fits 4 GB with room. |
| Biggest risk | Not RAM. It is **fusion weight creep** — a stochastic model quietly gaining influence over live decisions. Mitigated by KR-30..KR-34 (weight 0 until human promotion, same ladder as `MLEngine`). |

**Recommended path:** build phases **K0 → K2** (spec, offline trainer, shadow
sensor at fusion weight 0). Stop there. Re-evaluate K3+ only after a 2-week
shadow window produces a positive information coefficient.

---

## 2. What Kronos actually is (researched, 2026-08-11)

Facts established from the upstream repository and the AAAI-2026 paper record:

- **Type.** A decoder-only *foundation model* for K-line (OHLCV candlestick)
  sequences, pre-trained across data from 45+ global exchanges. Licensed **MIT**.
- **Two-stage design.**
  1. A **tokenizer** turns continuous OHLCV bars into *discrete hierarchical
     tokens* using **Binary Spherical Quantization (BSQ)**. A linear layer emits a
     `codebook_dim = s1_bits + s2_bits` vector; `s1` carries the coarse token and
     `s2` the fine refinement. Vocabulary is `2^s1_bits` per stream. Two decoder
     paths reconstruct from s1-only and from the full codebook.
  2. A **transformer** consumes the token pairs. `HierarchicalEmbedding` merges
     s1+s2 into `d_model`; `TemporalEmbedding` adds calendar features (minute,
     hour, weekday, day, month); a `DependencyAwareLayer` conditions the s2
     prediction on the *already-sampled* s1 token; a `DualHead` emits both logits.
- **Inference.** Per-channel z-score normalization `(x-mean)/(std+1e-5)` over 6
  channels (OHLCV + amount), clipped to ±5. Autoregressive loop over `pred_len`,
  temperature `T`, `top_p` nucleus filtering, `torch.multinomial` sampling,
  rolling window at `max_context`. `sample_count` trajectories are generated in
  parallel and **averaged**, then denormalized.
- **Sizes.** mini 4.1M / ctx 2048 · small 24.7M / ctx 512 · base 102.3M / ctx 512
  · large 499.2M (closed weights).

### 2.1 Published limitations — these drive our requirements

The upstream authors and reviewers state plainly:

- The bundled backtest **omits transaction costs, slippage, and risk-factor
  neutralization** — results are optimistic by construction.
- The finetuning pipeline is **a demonstration, not a production trading system**.
- The paper **does not claim profitable signals out of the box**; forecasting is
  necessary but not sufficient without portfolio optimization, risk management,
  and cost control.
- Finetune code comments were AI-generated and may be inaccurate.
- K-lines have **low signal-to-noise, strong non-stationarity, and complex
  cross-attribute dependencies**.

> **Consequence for us.** AIMOS already owns costs (`config/costs.yaml`),
> slippage (liquidity engine meta), sizing, and risk. So we need the part Kronos
> is genuinely good at — *the distribution of the next N bars* — and we must
> discard its evaluation posture entirely. Any Kronos-derived number that is
> validated without our own cost model is inadmissible (**KR-36**).

**Sources:** [upstream repo](https://github.com/shiyu-coder/Kronos) ·
[README](https://github.com/shiyu-coder/Kronos/blob/master/README.md) ·
[paper 2508.02739](https://arxiv.org/abs/2508.02739) ·
[OpenReview record](https://openreview.net/forum?id=sihn2VwAs4) ·
[independent review](https://jonathankinlay.com/2026/02/time-series-foundation-models-for-financial-markets-kronos-and-the-rise-of-pre-trained-market-models/)

---

## 3. Sourcing decision — why clean-room, not vendored

`vendor/VENDOR.md` already establishes the house pattern: vendored packages hold
**clean-room reference implementations written from public formulas/specs**, with
a `manifest.yaml` entry, a pinned SHA, and a `LICENSES/` record. Kronos is MIT, so
vendoring would be *legally* fine. We still decline, for four operational reasons:

| Reason | Detail |
|---|---|
| **Dependency weight** | Upstream requires `torch` + `huggingface_hub` + Qlib for the finetune path. `pyproject.toml` pins a deliberately lean runtime (§25.8). Adding torch to the trading runtime for one sensor is a bad trade at 4 GB. |
| **Weights are unreachable here** | `huggingface.co` and `arxiv.org` are **blocked by this environment's egress proxy**. A runtime that lazily downloads weights from HF cannot boot in our container, CI, or an air-gapped deploy. |
| **Pretraining corpus mismatch** | Kronos is pre-trained on equities-heavy global exchange data. Our universe is crypto majors + alts on binance/kraken/coinbase, 24/7, with funding and perp microstructure. Its calendar embedding (weekday/month) encodes a market-hours prior that is wrong for us. |
| **Determinism** | AIMOS is a *deterministic* system. Upstream sampling is `torch.multinomial` with no seed contract. We need bit-reproducible replay (**KR-20**). |

**Therefore:** implement `aimos/observation/forecast/` natively — BSQ-style
hierarchical quantizer + small causal transformer — trained on *our own* recorded
candles by *our own* walk-forward trainer. Cite Kronos as prior art in the module
docstring. No upstream code is copied; **KR-39** keeps the door open for an
out-of-process adapter if we ever want the real weights.

---

## 4. Hard constraints this work must not violate

Non-negotiable. Any design that trips one of these is rejected, not negotiated.

| # | Constraint | Where it bites |
|---|---|---|
| C1 | **Layer 1 never outputs a signal** (§0 rule 1) | The forecaster emits `Evidence` with `direction`/`strength` only. It must never return a p_up, a trade, or a size. |
| C2 | **`EngineOpinion.engine` is `Literal["rule","bayes","ml"]`** | Adding a 4th intelligence engine **requires editing `aimos/core/schemas.py`** — a standing-rule violation without explicit human approval. **This route is forbidden by default.** |
| C3 | **Evidence registry is frozen** (§25.6) | New names need explicit human approval. Registry order fixes the ML feature-vector width — adding names **invalidates every trained model** and mandates a retrain note in `specs/MODELS.md`. |
| C4 | **No hardcoded tunables** in `observation/` | Every threshold, horizon, temperature, and sample count lives in `config/`. `check_magic_numbers.py` scans this tree. |
| C5 | **All time via `clock.now()`** | No `datetime.now()`. Calendar features derive from bar timestamps, which are tz-aware. |
| C6 | **Import direction** `data → observation → intelligence → execution` | The forecaster lives in `observation/`; it may read `aimos.core` and `aimos.data`, and nothing above it. |
| C7 | **No LLM in the decision path** (§15.3) | Unaffected — this is an ML sequence model, not an LLM. Stated so nobody re-litigates it. |
| C8 | **No copyleft into `aimos/`** (§21.1) | torch is BSD-3, numpy BSD-3, Kronos MIT. Clean. `scripts/check_gpl_tripwire.py` stays green. |
| C9 | **Live path stays fail-closed** (§23.8) | The forecaster must not appear anywhere in the mandate, ladder, or boot-guard path. |
| C10 | **Per-engine isolation** (§10.1) | Return `[]` on insufficient data. Never raise. A missing/corrupt model file degrades to silence, not a crash. |
| C11 | **Anti-lookahead** (§9.1) | Only *closed* bars at or before `ctx.now`. The last, in-progress bar is excluded. Backtests use the same code path. |
| C12 | **Secrets never logged** | N/A today, but if KR-39's remote adapter lands, its endpoint token follows the existing secret-store rules. |

---

## 5. Gap analysis — what AIMOS lacks today

| Capability | Today | With this work |
|---|---|---|
| Forward price expectation | ❌ none — all 13 engines are backward-looking | ✅ median predicted drift over N bars |
| Predictive uncertainty | ❌ ATR is realized volatility, not forecast | ✅ P10/P50/P90 band from sampled paths |
| Path-shape / scenario sampling | ❌ backtester replays history only | ✅ sampled synthetic paths for stress tests |
| Microstructure anomaly detection | 🟡 partial (vol_shock, ignition) | ✅ tokenizer reconstruction error as an anomaly z |
| Sequence modeling in learning | ❌ `LogisticModel` / LightGBM on a flat feature vector | ✅ optional sequence features |

The honest framing: this adds **one genuinely new axis of information** (a
distribution over future bars). It does not fix anything currently broken.

---

## 6. Integration surface catalogue — every option, ranked

Twelve routes were considered. Verdicts are binding.

| ID | Route | Value | Disruption | Verdict |
|---|---|---|---|---|
| **A** | **Observation sensor** → `Evidence` into the bundle | High | Low | ✅ **Build (K2)** |
| **B** | **Forecast-band risk gate** → neutral-only evidence for stop/size context | High | Low | ✅ **Build (K2)** |
| **C** | **Anomaly sensor** — tokenizer reconstruction error | Medium | Low | ✅ **Build (K3)** |
| **D** | **Scenario generator** for backtest/stress (`config/scenarios.yaml`) | Medium | Low | ✅ **Build (K4)** — offline only, cannot touch live |
| **E** | **ML feature enrichment** — forecast features into `learning/features.py` | Medium | **High** | 🟡 **Gated** — changes feature width, forces full retrain (C3) |
| **F** | **Regime prior** into `intelligence/regime.py` | Medium | **High** | 🟡 **Gated** — Layer-2 change, needs a fusion re-validation |
| **G** | **Universe pre-ranking** by cross-sectional forecast IC | Medium | Medium | 🟡 **Defer to K5** — mirrors `factor_engine`; needs cross-sectional training data |
| **H** | **UI: forecast fan chart** + mindmap node | Medium | Low | ✅ **Build (K3)** — read-only |
| **I** | **AI-analyst grounding** — forecasts in `/ask`, `/report` | Low | Low | ✅ **Build (K4)** — read-only, `specs/ASSISTANT.md` rules apply |
| **J** | **4th intelligence engine** (`EngineOpinion(engine="forecast")`) | Medium | **Severe** | ❌ **Rejected** — violates C2 |
| **K** | **Execution TP/SL from predicted quantiles** | High | **Severe** | ❌ **Rejected for now** — plugins consume `MarketUnderstanding` only; would need a contract change |
| **L** | **Out-of-process real-Kronos adapter** (§21.1 pattern) | Optional | Low | 🟡 **Interface only (KR-39)** — define the port, build no client |

Routes **J** and **K** are the tempting ones and both are traps: J needs a
`schemas.py` edit, K needs execution to consume a forecast the evaluator was never
validated against. Neither is worth it for a model at fusion weight 0.

---

## 7. Requirements

### 7.1 Model & training — KR-1..KR-9

- **KR-1 — Native implementation.** Implement under `aimos/observation/forecast/`
  with `quantizer.py`, `sequence_model.py`, `predictor.py`, `engine.py`. Module
  docstrings cite Kronos (arXiv 2508.02739, MIT) as prior art and state that no
  upstream code was copied.
- **KR-2 — Hierarchical quantizer.** BSQ-style two-stream discretization of each
  bar. Default `s1_bits: 8`, `s2_bits: 8` → 256 rows per stream, 65 536 effective
  bar codes. Both bit widths are config keys, not constants.
- **KR-3 — Input channels.** Five channels: open, high, low, close, volume. The
  `amount` channel is **omitted** — we do not have it reliably across venues.
  Synthetic gap-filled bars are excluded via `real_candles()` before encoding.
- **KR-4 — Normalization.** Per-window, per-channel z-score with an epsilon, clip
  to ±`clip` (default 5.0), all from config. Volume is log1p-transformed before
  z-scoring (crypto volume is heavy-tailed; raw z-scores saturate the clip).
- **KR-5 — Model size.** Causal decoder: `d_model: 128`, `n_layers: 4`,
  `n_heads: 4`, `context_bars: 256`. Target ≈ 1.2M params ≈ 5 MB fp32.
  Every dimension is a config key. **The model must never exceed 8M params without
  a documented RAM re-measurement (KR-15).**
- **KR-6 — Temporal features.** Calendar embedding uses **UTC hour + weekday only**.
  Month/day-of-month are dropped — crypto has no earnings calendar and they invite
  spurious seasonality on our short history.
- **KR-7 — Dual head with dependency.** s2 logits are conditioned on the sampled
  s1 token, per the hierarchical design. This is the one architectural detail worth
  copying exactly; a naive independent-head factorization loses the intra-bar
  OHLC coherence and produces bars where `high < close`.
- **KR-8 — Trainer is offline only.** `scripts/train_forecaster.py`, mirroring
  `scripts/train_from_history.py`. It must **never** be importable from the serve
  loop. Walk-forward split only — reuse `learning/train.py::assert_temporal_split`.
  Random splits are forbidden.
- **KR-9 — Weight artifact format.** Trained weights export to a **`.npz` of plain
  arrays** plus a JSON sidecar (`schema_version`, config hash, training window,
  bar count, validation metrics, git SHA). The runtime loads the `.npz`. Torch, if
  used at all, is confined to the training script behind an optional extra.

### 7.2 Runtime footprint — KR-10..KR-16 (the 4 GB budget)

- **KR-10 — No torch in the trading runtime.** Inference is **pure numpy**.
  Rationale: a 4-layer/128-dim causal transformer is ~15 lines of matmul per layer;
  importing torch to run it costs ~200 MB of installed wheel and ~250 MB RSS for no
  benefit. Torch, if the trainer wants it, goes in a new `forecast-train` optional
  extra that the runtime image does not install.
- **KR-11 — RSS budget.** Added resident memory ≤ **350 MB** measured at steady
  state with the full universe loaded. Hard fail the acceptance gate above 500 MB.
- **KR-12 — Latency budget.** ≤ **50 ms p95** per symbol·timeframe for
  `pred_len × sample_count` = 12 × 16. Measured on one CPU core.
- **KR-13 — Per-bar caching.** Inference is keyed on
  `(symbol, timeframe, last_closed_bar_timestamp, config_hash)`. Within one bar the
  result is reused across ticks. This is what actually makes the budget hold —
  without it, cost scales with tick rate instead of bar rate.
- **KR-14 — Bounded concurrency.** Forecasting runs on a bounded thread pool with a
  config'd worker count (default 1). No unbounded fan-out over the universe.
- **KR-15 — Measured, not asserted.** A `tests/observation/test_forecast_budget.py`
  asserts param count, artifact size on disk, and p95 latency. RAM is measured and
  recorded in `specs/OPERATIONS.md` at implementation time.
- **KR-16 — Graceful absence.** Missing `.npz`, schema-version mismatch, or config-
  hash mismatch → engine logs once at WARN and returns `[]` forever after. It never
  loads a stale-schema artifact and never raises (C10).

### 7.3 Determinism & correctness — KR-17..KR-22

- **KR-17 — Closed bars only.** The encoder window ends at the last bar whose close
  time ≤ `ctx.now`. The in-progress bar is excluded (C11).
- **KR-18 — Backtest parity.** Live and backtest share one code path. A test asserts
  identical evidence for identical `MarketContext` under both clocks.
- **KR-19 — No future leakage in normalization.** Window statistics come from the
  lookback window only — never from the full series, never from the prediction
  horizon. This is the single most common way forecasting code silently cheats;
  it gets a dedicated test.
- **KR-20 — Seeded sampling.** The path sampler is seeded from a hash of
  `(symbol, timeframe, last_closed_bar_timestamp, config_hash)`. Same bar → same
  paths → same evidence, forever. **This is what makes a stochastic model
  admissible in a deterministic system.**
- **KR-21 — Bar coherence.** Every sampled bar must satisfy
  `low ≤ min(open,close) ≤ max(open,close) ≤ high` after denormalization.
  Violations are counted and reported; a sample-level violation rate above a
  config'd ceiling fails the training acceptance gate.
- **KR-22 — Aggregation is quantile-based, not mean.** Upstream averages the sampled
  paths. Averaging discards exactly the information we want. We retain **P10 / P50 /
  P90 per horizon step** plus the sign-agreement fraction.

### 7.4 Evidence contract — KR-23..KR-29

- **KR-23 — Registry additions require explicit human approval** (C3). Proposed:

  | Name | Semantics | Meaning |
  |---|---|---|
  | `forecast_drift` | DIRECTIONAL | median (P50) predicted log-return over the horizon, z-scored against realized bar-return σ |
  | `forecast_agreement` | DIRECTIONAL | fraction of sampled paths agreeing on terminal sign, remapped to 0..1 |
  | `forecast_band` | NEUTRAL_ONLY | (P90−P10) expressed as an ATR multiple — a risk/uncertainty gate |
  | `forecast_anomaly` | NEUTRAL_ONLY | tokenizer reconstruction-error z-score (route C) |

- **KR-24 — Retrain note mandatory.** Because registry order fixes the ML feature-
  vector width (§25.6), the same PR that adds these names must add the retrain note
  to `specs/MODELS.md` and state that existing `LogisticModel` artifacts are
  invalidated.
- **KR-25 — Source naming.** `source = "forecast_engine.<name>"`, matching the
  existing `<engine>.<name>` convention.
- **KR-26 — Reliability prior.** `config/weights.yaml` gets
  `reliability.forecast_engine: 0.35`. Deliberately low — below `sentiment` (0.40)
  and near `time` (0.35). An unvalidated forecaster should start as one of the
  least-trusted sensors in the system, and rise only on evidence.
- **KR-27 — Strength is calibrated, not raw.** `strength` derives from the model's
  *measured* validation skill, not from its raw confidence. A model with IC ≈ 0
  must emit strength ≈ 0 even when it is loudly certain. Uncalibrated softmax
  confidence is the primary failure mode of this class of model.
- **KR-28 — Emit nothing when uninformative.** Below a config'd `min_agreement` or
  `min_abs_drift_z`, emit no directional evidence at all — matching how
  `MomentumEngine` stays silent inside the RSI 45–55 band.
- **KR-29 — Meta payload.** `meta` carries `{p10, p50, p90, horizon_bars,
  agreement, model_version, config_hash}` for the UI, the mindmap, and the journal.

### 7.5 Fusion, promotion, and safety — KR-30..KR-36

- **KR-30 — Zero influence at launch.** Ships behind `features.forecast_enabled:
  false`. Enabled, it emits evidence into the bundle but contributes **no** fusion
  weight of its own; it reaches Layer 2 only through the existing rule/bayes
  evidence-weighting path, at reliability 0.35.
- **KR-31 — Promotion ladder = the ML ladder** (§8.3). Walk-forward validation only
  → directional IC > 0 and calibration (Brier) improving on held-out data → **2-week
  shadow window** → a human raises the reliability in config → restart. No auto-
  promotion. `shadow_weight()` semantics apply.
- **KR-32 — Model risk register.** A `specs/MODELS.md` row is added at K2 with
  purpose, inputs, training window, calibration status, weight, owner, failure
  modes, and demotion triggers (§24.6).
- **KR-33 — Drift demotion** (§23.7). PSI > 0.25 on the input distribution → a
  retraining *proposal*, never an auto config write. Brier degradation > 20% →
  reliability auto-halves. Automated moves are permitted only toward caution.
- **KR-34 — Kill switch.** `features.forecast_enabled: false` fully removes the
  engine from `build_engines()`. No import, no artifact load, no thread pool.
- **KR-35 — Live path untouched.** No change to mandate, go-live ladder, boot guard,
  broker, or router. A grep-based test asserts `aimos/execution/` contains no
  reference to the forecast module.
- **KR-36 — Costs mandatory in any evaluation.** Every backtest or run card
  involving the forecaster applies `config/costs.yaml` fees and liquidity-engine
  slippage. A cost-free evaluation is inadmissible — this is the specific upstream
  failure we refuse to inherit (§2.1).

### 7.6 Config, ops, and interfaces — KR-37..KR-42

- **KR-37 — Config surface.** New `config/forecast.yaml`, env-overridable as
  `AIMOS__FORECAST__*`:

  ```yaml
  forecast:
    model_path: "~/.aimos/models/forecast/v1.npz"
    timeframes: ["15m", "1h"]      # which tf to forecast; keep narrow for budget
    context_bars: 256
    horizon_bars: 12
    sample_count: 16
    temperature: 1.0
    top_p: 0.9
    clip: 5.0
    max_workers: 1
    quantizer: { s1_bits: 8, s2_bits: 8 }
    model: { d_model: 128, n_layers: 4, n_heads: 4 }
    emit:
      min_agreement: 0.60          # below → emit no directional evidence
      min_abs_drift_z: 0.25
      band_atr_cap: 3.0            # forecast_band strength saturation
  ```

- **KR-38 — Feature flag.** `features.forecast_enabled: false` in
  `config/default.yaml`, documented in `specs/OPERATIONS.md` §4 alongside the other
  dormant features.
- **KR-39 — Remote adapter interface (design only).** Define a `ForecastProvider`
  protocol (`forecast(symbol, timeframe, bars) -> ForecastResult`) with the native
  implementation as the sole concrete class. This preserves the §21.1 escape hatch:
  a real-Kronos HTTP service could be added later as a second implementation without
  importing torch or upstream code into `aimos/`. **Build the protocol; build no
  client.**
- **KR-40 — Dashboard (route H).** A read-only fan chart (P10/P50/P90 vs realized)
  on the Decision Anatomy screen and a forecast node in `/mindmap`. Read-only, no
  controls, hidden when the flag is off.
- **KR-41 — Journal.** Forecast evidence is journaled like any other, so the
  hash-chained record supports after-the-fact IC scoring without a separate store.
- **KR-42 — Documentation duties.** On implementation: `CHANGELOG.md` entry,
  `specs/STATUS.md` state move, `specs/OPERATIONS.md` flag + env vars + RAM
  measurement, `specs/MODELS.md` register row, `specs/ARCHITECTURE.md` section
  reference for the new engine.

---

## 8. Rollout ladder

Each phase has a gate. **Do not start a phase until the previous gate passes.**

| Phase | Deliverable | Gate to exit |
|---|---|---|
| **K0** | This document, reviewed and approved | Human sign-off on the evidence-registry additions (KR-23) and on the model-size ceiling (KR-5) |
| **K1** | Quantizer + model + numpy inference + `scripts/train_forecaster.py`. **No engine, no config, not wired in.** | Reconstruction error beats a naive last-bar-carry baseline; bar-coherence violations under ceiling (KR-21); param/latency/size budgets measured (KR-15) |
| **K2** | `ForecastEngine` (routes A + B) behind the flag, at reliability 0.35 | Full suite green; magic-number, naive-datetime, import-linter clean; 2-week shadow shows directional IC > 0 **with costs applied** (KR-36) |
| **K3** | Anomaly evidence (C) + dashboard fan chart (H) | Read-only; no change to any decision |
| **K4** | Scenario generator (D) + analyst grounding (I) | Offline/read-only only; backtester results unchanged when the flag is off |
| **K5** | Re-evaluate E / F / G with real shadow data in hand | Fresh approval — each requires re-validating fusion |

**If K2's shadow window shows IC ≤ 0, stop and delete the engine.** A forecaster
that does not forecast is worse than no forecaster, because it consumes RAM,
latency, and — most expensively — attention.

---

## 9. Test plan

| Area | Test |
|---|---|
| Anti-lookahead | Evidence at bar *t* is byte-identical whether or not bars > *t* exist in the frame (KR-17, KR-19) |
| Determinism | Same context → same evidence across processes and runs (KR-20) |
| Backtest parity | Live clock vs backtest clock produce identical evidence (KR-18) |
| Bar coherence | Sampled OHLC ordering invariants hold (KR-21) |
| Graceful degradation | Missing / corrupt / wrong-schema artifact → `[]`, one WARN, no raise (KR-16) |
| Isolation | An exception inside the engine is swallowed by `run_all`; the bundle still assembles (§10.1) |
| Silence | Below-threshold forecasts emit nothing (KR-28) |
| Budget | Param count, artifact bytes, p95 latency (KR-15) |
| Flag off | With `forecast_enabled: false`, `build_engines()` output and all golden fixtures are unchanged |
| Golden example | §25.9 worked example still reproduces exactly (fusion 0.766/0.428; NO_TRADE, EV −0.018) |
| Live isolation | No `aimos/execution/` reference to the forecast module (KR-35) |
| Lints | `check_magic_numbers`, `check_no_naive_datetime`, `lint-imports`, `check_gpl_tripwire` |

---

## 10. Failure modes

| Failure | Detection | Response |
|---|---|---|
| Overconfident but skill-less | Validation IC ≈ 0 with high agreement | KR-27 calibration forces strength → 0 |
| Regime shift after training | PSI on input distribution | KR-33 retraining proposal |
| Silent lookahead | KR-19 test + walk-forward-only trainer | Blocks the K1 gate |
| RAM creep from model growth | KR-15 assertion | Hard-fails CI |
| Latency blowup across a wide universe | KR-12/KR-13 | Per-bar cache; narrow `timeframes` |
| Weight creep into decisions | Config review | KR-30/KR-31 ladder; reliability is a config value, never code |
| Stale artifact after a config change | Config-hash check | KR-16 refuses to load |

---

## 11. Explicit non-goals

1. **Not** cloning, vendoring, or pip-installing Kronos.
2. **Not** downloading Hugging Face weights (egress-blocked; also a boot dependency we refuse).
3. **Not** adding torch to the trading runtime (KR-10).
4. **Not** adding a 4th `EngineOpinion` engine (C2).
5. **Not** letting execution plugins consume forecasts (route K).
6. **Not** auto-promoting the model to nonzero influence (KR-31).
7. **Not** changing the live-order path in any way (KR-35).
8. **Not** re-implementing Kronos's cost-free backtest posture (KR-36).

---

## 12. Open questions for the operator

1. **Registry approval (KR-23).** Approve the four evidence names? Adding them
   invalidates existing trained `LogisticModel` artifacts and forces a retrain.
2. **Training data.** The 12-month recorded dataset (P1-T6) is still listed as *not
   built* in `specs/STATUS.md`. K1 needs it, or needs `scripts/download_history.py`
   run first. **This is the real blocker** — everything else here is tractable.
3. **Timeframe scope.** Start with `15m`+`1h` only? 1m multiplies cost by ~15× for
   the noisiest, least forecastable horizon.
4. **Universe scope.** Majors only at K2, or the full tiered universe?
5. **Deployment target.** Is the 4 GB host the Coolify deploy? If so, confirm the
   headroom after TimescaleDB and the API process.

---

## 13. Bottom line

Kronos is a real and well-executed piece of work, and the gap it fills in AIMOS is
real: we have no forward-looking distributional view. But its value to us is
**conceptual, not literal** — the tokenizer/decoder recipe is worth reproducing at
1/20th the size; its weights, dependencies, calendar priors, and cost-free
evaluation posture are not.

The build is small (~1.2M params, numpy inference, ≈5 MB on disk). The discipline
is the hard part: it must enter as the *least-trusted sensor in the system*, at
fusion weight 0, behind a flag, on the same promotion ladder that has correctly
kept `MLEngine` inert since Phase 3 — and it must be deleted without ceremony if
the shadow window says it has no skill.
