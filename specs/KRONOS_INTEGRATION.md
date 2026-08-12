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

**Recommended path:** **do not start K1 yet.** Close the measurement loop first
(`specs/TASKS.md` T-001) and land the 12-month costed backtest (T-003) — the
forecaster's own exit gate is unevaluable without them (§8). Then build **K1 → K2**
(offline trainer, shadow sensor at fusion weight 0) and stop. Re-evaluate K3+ only
after a 2-week shadow window produces a positive information coefficient.

**K0 — the operator sign-off in §12 — is startable today and is the only part that
is.** It is a decision, not code.

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

### 2.0.1 Implementation detail (read from upstream `model/module.py`)

Enough detail to reimplement without reference to their code:

**BSQ quantizer.** Embeddings are quantized to binary codes `{−1, +1}` with a
straight-through estimator — `z + (zhat − z).detach()` — so gradients flow through
the round. `bits_to_indices()` converts binary vectors to integer indices via
powers of two; with `half=True` it processes `s1_bits` and `s2_bits` as separate
levels. Training loss has three parts: a **commitment** term
`beta · mean((zq.detach() − z)²)`, and **entropy** terms weighted by `gamma0`
(per-sample) and `gamma` (codebook), scaled by `zeta`. Soft entropy splits codes
into subgroups (`group_size`, default 9) and softmaxes distances to a group
codebook at `inv_temperature`. The entropy terms are what stop codebook collapse —
without them most codes go unused and the tokenizer degenerates.

**Hierarchical embedding.** Composite token IDs split bitwise:
`s2_ids = t & ((1 << s2_bits) − 1)`, `s1_ids = t >> s2_bits`. Each embeds
separately, scales by `√d_model`, then concatenates and projects back to `d_model`
through a fusion layer.

**Dependency-aware layer.** Cross-attention where the **sibling embedding is the
query** and the hidden states are key/value, followed by residual + RMSNorm. This
is how s2 sees the sampled s1.

**Dual head.** `proj_s1` → `2^s1_bits` logits, `proj_s2` → `2^s2_bits` logits;
separate cross-entropy losses, averaged, respecting a padding mask.

**Transformer block.** Pre-norm **RMSNorm**; **RoPE** rotary position embeddings on
q/k; `F.scaled_dot_product_attention` with a causal mask; **SwiGLU** feed-forward
`w2(silu(w1(x)) ⊙ w3(x))` with no biases (`ff_dim` default 1024).

**Temporal embedding.** Separate tables for minute (60), hour (24), weekday (7),
day (32), month (13), summed and projected to `d_model`; sinusoidal `FixedEmbedding`
by default, learnable when `learn_pe=True`.

> All of RMSNorm, RoPE, and SwiGLU are standard modern-transformer parts with
> closed-form definitions. They are ~40 lines of numpy each for **inference**,
> which is what makes KR-10 (no torch in the runtime) realistic rather than
> aspirational.

**Reference usage.** Their `prediction_example.py` runs `lookback=400`,
`pred_len=120`, `T=1.0`, `top_p=0.9`, `sample_count=1`, with OHLCV **+ amount**
columns and timestamps passed as separate history/future series.

### 2.0.2 Their real training/inference settings (from `finetune/config.py`)

The demo defaults are **not** what they use for evaluation. Worth calibrating
against:

| Setting | Demo (`prediction_example.py`) | Finetune/backtest (`config.py`) |
|---|---|---|
| Lookback | 400 | **90** |
| Prediction length | 120 | **10** |
| Temperature `T` | 1.0 | **0.6** |
| `top_p` / `top_k` | 0.9 / — | 0.9 / 0 |
| `sample_count` | 1 | **5** |

Training: 30 epochs, batch 50/GPU, 100k samples/epoch, AdamW (β₁ 0.9, β₂ 0.95,
weight-decay 0.1), LR **2e-4 tokenizer / 4e-5 predictor**, clip 5.0, seed 100.
Corpus: **CSI300 Chinese equities**, 2011-01-01 → 2025-06-05, walk-forward split
(train ≤ 2022-12, test 2024-04 →).

**Three things this changes for us:**

1. **Lower the temperature.** KR-37's default of `T: 1.0` follows the demo; their
   own evaluation uses **0.6**. Lower temperature means less sampling noise, which
   matters more for us than for them because KR-20 requires reproducibility and
   KR-22 keeps quantiles rather than a mean. **Adopt `temperature: 0.6` as the
   config default.**
2. **A shorter context is defensible.** They finetune at lookback **90**, not 400.
   Our `context_bars: 256` (KR-5) sits comfortably between, and 128 would still be
   within their demonstrated range if the latency budget (KR-12) needs relief.
3. **The horizon should be short.** They predict **10 bars** in the setting they
   actually evaluate. Our `horizon_bars: 12` (KR-37) is consistent. Resist the
   temptation to forecast further — their own 120-bar demo is not the configuration
   they trust.

**Dependency confirmation** (`requirements.txt`): `torch>=2.0.0`,
`huggingface_hub==0.33.1`, `safetensors==0.6.2`, `einops==0.8.1`,
`matplotlib==3.9.3`, `pandas==2.2.2`, `tqdm`, `numpy`. This is the full weight of
what vendoring would pull in — and note `pandas==2.2.2` conflicts with our pinned
`2.2.3` (§25.8, no floating ranges). Further support for KR-10 (numpy-only
inference) and §3 (clean-room, not vendored).

> **Corpus caveat, now confirmed.** They finetune on **CSI300 equities** — a
> market with fixed trading hours, daily auctions, price limits, and a weekday
> calendar. That is precisely the prior encoded in their `TemporalEmbedding`
> (minute/hour/weekday/day/month), and precisely why KR-6 drops month and
> day-of-month for a 24/7 crypto market.
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

## 3. Sourcing decision — Option A (clean-room, recommended default) vs Option B (real weights, operator-provided)

`vendor/VENDOR.md` already establishes the house pattern: vendored packages hold
**clean-room reference implementations written from public formulas/specs**, with
a `manifest.yaml` entry, a pinned SHA, and a `LICENSES/` record. Kronos is MIT, so
using its actual weights is *legally* fine.

**Important correction (2026-08-12):** an earlier version of this document listed
"weights are unreachable" as one of four reasons to reject Kronos's real model
outright. That reason was wrong to include as an architectural verdict — it was
true only of the sandboxed development session that wrote this spec, verified
directly:

```
$ curl https://huggingface.co        → CONNECT tunnel failed, response 403
$ curl https://data.binance.vision   → CONNECT tunnel failed, response 403
$ pip install huggingface_hub        → succeeds (PyPI is not restricted)
```

That 403 is this development sandbox's own egress policy, not a property of
Kronos, of AIMOS, or of the operator's machine, CI runner, or deploy target. **The
operator can fetch these files** — see §3.2. Ruling out an entire capability
because *this session* can't reach a domain, without saying so, is exactly the
kind of silent gap this document should not have. Reclassified below into what
actually still holds and what is now an operator-provided option.

### 3.1 Reasons that hold regardless of who downloads the weights

These are not environment limits — they hold even if the `.safetensors` files are
sitting in the repo tomorrow:

| Reason | Detail |
|---|---|
| **Dependency weight** | Upstream requires `torch>=2.0.0` + `huggingface_hub` + Qlib for the finetune path (confirmed, `requirements.txt`, §2.0.2). `pyproject.toml` pins a deliberately lean runtime (§25.8). Adding torch to the **trading runtime process** for one sensor is a bad trade at 4 GB — this is about where torch runs, not whether the weights exist. |
| **Pretraining corpus mismatch** | Kronos's finetune corpus is CSI300 — Chinese equities, fixed trading hours, confirmed via `finetune/config.py` (§2.0.2). Our universe is crypto majors + alts on binance/kraken/coinbase, 24/7, with funding and perp microstructure. Its calendar embedding (weekday/month) encodes a market-hours prior that is wrong for us — **downloading the weights doesn't retrain them on the right market.** |
| **Determinism** | AIMOS is a *deterministic* system. Upstream sampling is `torch.multinomial` with no seed contract. We need bit-reproducible replay (**KR-20**) — a property of the inference code, not of where the weights came from. |
| **`pandas==2.2.2` pin conflicts** | Upstream pins `pandas==2.2.2`; AIMOS pins `2.2.3` (§25.8, no floating ranges). Resolvable, but real. |

**Recommendation stands: Option A, the AIMOS-native clean-room model (§7.1, KR-1
onward), is still the better default** — not because the real weights are
unreachable, but because even with them in hand, they'd need refitting to a
different market, isolating from the trading process, and reconciling with a
determinism guarantee that upstream doesn't provide. Option A is smaller
(~1.2M params vs. even Kronos-mini's 4.1M), trained on the right corpus from day
one, and numpy-only by construction.

### 3.2 Option B — using the real Kronos weights (operator action required)

If the operator wants to try the actual pretrained model — e.g. to compare
against Option A's output before committing to a full build-out — here is the
concrete path. **Nothing below can be done from this development sandbox; every
step needs the operator or a differently-provisioned environment.**

> #### ⚠️ OPERATOR ACTION NEEDED
>
> 1. **Download the weights** from a machine with Hugging Face access:
>    ```bash
>    pip install huggingface_hub
>    huggingface-cli download NeoQuasar/Kronos-Tokenizer-base --local-dir kronos_weights/tokenizer
>    huggingface-cli download NeoQuasar/Kronos-small --local-dir kronos_weights/model
>    ```
>    (`Kronos-mini`/`Kronos-Tokenizer-2k` for the 4.1M-param variant, ctx 2048, if
>    footprint matters more than accuracy — see the size table in §2.)
> 2. **Add them to the repo** — as a new `vendor/kronos_weights/` path (weights are
>    binary artifacts; consider Git LFS) with a `manifest.yaml` entry per
>    `vendor/VENDOR.md`'s existing pattern, recording the exact HF revision/commit
>    downloaded.
> 3. **Install the inference-only extra** — `torch`, `einops`, `safetensors` as a
>    **new, separate** `pyproject.toml` optional-dependency group (e.g. `[kronos]`),
>    never added to the base install or the `runtime`/`serve` extras that the
>    trading process installs.
> 4. **Run it out-of-process** — per **KR-39**, as an HTTP microservice the
>    `ForecastProvider` protocol calls, so torch and the weights never enter the
>    `aimos` trading process's dependency graph or memory footprint. This is the
>    one requirement that doesn't relax even with the weights in hand — §4 C6
>    (import direction) and the 4 GB RSS budget (KR-11) both still apply, and an
>    out-of-process service is how a torch-based model coexists with either.
> 5. **Report back what it evaluates to** — with the same costed backtest harness
>    (T-003) and the same shadow-window IC gate (KR-31) as Option A, so the two are
>    comparable on identical terms rather than one being trusted more just because
>    the weights are "real."
>
> Once weights exist at `vendor/kronos_weights/`, tell me — I'll finish wiring the
> `ForecastProvider` HTTP client (KR-39), the microservice Dockerfile, and the
> comparison harness. What I cannot do myself is step 1.

**This does not change the K0–K5 rollout ladder or its blockers.** Option B still
needs T-001 (outcomes loop) and T-003 (costed backtest with real history — itself
partially operator-blocked, see §12.1 below) before either model's shadow window
can be scored. Fetching the weights early is fine and lets Option A vs. B be
compared the moment the loop closes; it does not let either skip the gate.

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
    sample_count: 16              # > their 5: we keep quantiles, not a mean (KR-22)
    temperature: 0.6              # their evaluated setting, not the demo's 1.0 (§2.0.2)
    top_p: 0.9
    top_k: 0
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

### 7.7 Correlation control — KR-43 (added after review)

- **KR-43 — Extend the correlation guard to cover the forecaster.**

  `aimos/intelligence/bayes_engine.py:67` already halves the reliability of a
  *same-engine* evidence tail, so one chatty engine cannot drown the rest:

  ```python
  """Return (evidence, reliability_factor) with same-engine tail halved."""
  ```

  **That guard keys on the engine name, and the forecaster would evade it.** A
  forecaster reads OHLCV candles — and so do `momentum`, `price_action`,
  `volatility`, and `volume`. `forecast_drift` would substantially *re-derive*
  what those four engines already reported, then be counted again as an
  independent voice under a new name.

  The failure mode is not one engine dominating. It is **the same information
  counted twice**, which raises `confidence` without raising accuracy. Since
  confidence gates trade eligibility (`min_confidence` in `config/scalp.yaml`,
  §6.7 meta-confidence), inflated confidence directly loosens risk control. That
  is strictly more dangerous than a weak signal.

  **Requirement:** the correlation guard must group by *information family*, not
  engine name. `forecast_drift` joins the `{momentum, price_action}` family and is
  discounted against it. `forecast_band` and `forecast_anomaly` do **not** — they
  carry genuinely new information (forward range, reconstruction error) that no
  existing engine produces.

  **Corollary worth stating plainly:** the *uncertainty* half of the forecaster is
  the valuable half. Nothing in AIMOS currently forecasts forward volatility — ATR
  is realized volatility, and it sets every stop and target in every plugin
  (`funding_rate.py:41`, `breakout.py:44`, `mean_reversion.py:37`). The direction
  half is mostly a repackaging of signals we already have. Prioritize accordingly:
  if only one evidence name survives review, keep `forecast_band`.

---

## 8. Rollout ladder

> ### ⛔ Hard blocker — read before starting anything
>
> **K2's exit gate cannot be evaluated today.** It requires *"directional IC > 0
> with costs applied"* over a 2-week shadow window (KR-31, KR-36). Computing an
> information coefficient requires knowing what actually happened after each
> forecast — i.e. the `outcomes` table.
>
> That table is **empty**, and `Journal.write_outcome()`
> (`aimos/journal/journal.py:101`) is called by **zero production code**. The
> measurement loop has never closed once:
>
> ```
> decisions   2760
> outcomes       0
> ```
>
> **`specs/TASKS.md` T-001 is therefore a hard prerequisite for this entire
> programme**, not an adjacent nicety. Building the forecaster first produces a
> model that nobody — not a human, not the analyst, not the promotion ladder — can
> score. It would sit at reliability 0.35 forever, because the evidence needed to
> move it could not be gathered.
>
> Likewise **T-003** (12-month costed backtest) is a prerequisite for K1: the
> trainer has no data without it, and there is no baseline to beat.

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

Every requirement that can fail silently gets a test. Grouped by phase, with the
requirement each case defends.

**New test files:** `tests/test_forecast_quantizer.py`,
`tests/test_forecast_model.py`, `tests/test_forecast_engine.py`,
`tests/test_forecast_budget.py`.

### 9.1 Quantizer (K1) — `tests/test_forecast_quantizer.py`

| ID | Test | Assert | Defends |
|---|---|---|---|
| KT-01 | Round-trip encode→decode on real candles | reconstruction error below a configured ceiling | KR-2 |
| KT-02 | Codebook utilization over 10k bars | > 50% of codes used — catches codebook collapse | KR-2 |
| KT-03 | Bitwise split/merge | `s1 = t >> s2_bits`, `s2 = t & ((1<<s2_bits)−1)` round-trips exactly | KR-2 |
| KT-04 | Volume log1p transform | heavy-tailed volume does not saturate the ±clip bound | KR-4 |
| KT-05 | Synthetic bars excluded | gap-filled candles never reach the encoder | KR-3 |
| KT-06 | Constant-price window | zero variance → no NaN, no divide-by-zero | KR-4 |
| KT-07 | Determinism | same bars → identical tokens, twice, across processes | KR-20 |

### 9.2 Model + sampling (K1) — `tests/test_forecast_model.py`

| ID | Test | Assert | Defends |
|---|---|---|---|
| KT-10 | **Anti-lookahead** — bars after *t* present vs absent | byte-identical output | **KR-17, KR-19** |
| KT-11 | **Normalization window** — stats from lookback only | changing future bars does not change normalization | **KR-19** |
| KT-12 | Seeded sampling | same `(symbol, tf, bar_ts, config_hash)` → identical paths | KR-20 |
| KT-13 | Different bar timestamp | different paths (seed actually varies) | KR-20 |
| KT-14 | **Bar coherence** | `low ≤ min(o,c) ≤ max(o,c) ≤ high` on every sampled bar | **KR-21** |
| KT-15 | Quantile aggregation | P10 ≤ P50 ≤ P90; not a mean | KR-22 |
| KT-16 | Beats naive baseline | reconstruction beats last-bar-carry | K1 gate |
| KT-17 | Param-count ceiling | ≤ 8M params | KR-5 |
| KT-18 | Calendar features | UTC hour + weekday only; no month/day leakage | KR-6 |
| KT-19 | s2 conditioned on s1 | changing sampled s1 changes s2 logits | KR-7 |
| KT-20 | Artifact round-trip | `.npz` + JSON sidecar saves and loads identically | KR-9 |
| KT-21 | Numpy-only inference | `torch` is not imported anywhere under `aimos/` | **KR-10** |

### 9.3 Engine integration (K2) — `tests/test_forecast_engine.py`

| ID | Test | Assert | Defends |
|---|---|---|---|
| KT-30 | Flag off | `build_engines()` output unchanged; no artifact load, no import | **KR-34** |
| KT-31 | Missing artifact | `[]`, exactly one WARN, no raise | KR-16 |
| KT-32 | Corrupt artifact | same — degrades to silence | KR-16 |
| KT-33 | Schema-version mismatch | refuses to load stale artifact | KR-16 |
| KT-34 | Config-hash mismatch | refuses to load | KR-16 |
| KT-35 | Engine raises internally | `run_all` swallows it; bundle still assembles | §10.1, KR-16 |
| KT-36 | Below `min_agreement` | emits nothing | KR-28 |
| KT-37 | Below `min_abs_drift_z` | emits nothing | KR-28 |
| KT-38 | Unregistered evidence name | `Evidence` construction raises | KR-23, §25.6 |
| KT-39 | Source naming | every source is `forecast_engine.<name>` | KR-25 |
| KT-40 | Reliability wiring | engine uses 0.35 from `weights.yaml`, not a literal | KR-26 |
| KT-41 | **Calibration** — model with IC ≈ 0 | `strength` ≈ 0 despite high raw confidence | **KR-27** |
| KT-42 | `meta` payload | carries p10/p50/p90/horizon/agreement/version/hash | KR-29 |
| KT-43 | **Correlation guard** | `forecast_drift` discounted against momentum/price_action family | **KR-43** |
| KT-44 | `forecast_band` not discounted | independent information keeps full weight | KR-43 |
| KT-45 | **Confidence does not inflate** | adding forecast evidence to a fixed bundle does not raise §6.7 meta-confidence beyond a bound | **KR-43** |
| KT-46 | Backtest parity | live clock vs backtest clock → identical evidence | KR-18 |
| KT-47 | Per-bar cache | N ticks within one bar → exactly 1 inference call | KR-13 |
| KT-48 | Cache key varies | new closed bar → new inference | KR-13 |
| KT-49 | **Golden example** | §25.9 reproduces exactly (fusion 0.766/0.428; NO_TRADE, EV −0.018) | no regression |
| KT-50 | **Live isolation** | no `aimos/execution/` reference to the forecast module | **KR-35** |
| KT-51 | Fusion weight | forecaster contributes no `EngineOpinion`; `p_up` still fused from rule/bayes/ml only | KR-30, C2 |

### 9.4 Budget (K2) — `tests/test_forecast_budget.py`

| ID | Test | Assert | Defends |
|---|---|---|---|
| KT-60 | Artifact size on disk | ≤ 8 MB | KR-9, KR-11 |
| KT-61 | p95 latency, 12×16 | ≤ 50 ms single core | KR-12 |
| KT-62 | Bounded concurrency | worker count never exceeds config | KR-14 |
| KT-63 | RSS delta, full universe | ≤ 350 MB; hard fail above 500 MB | **KR-11** |

### 9.5 Repo-wide gates (every phase)

| Check | Command |
|---|---|
| Full suite | `python -m pytest` |
| Magic numbers | `python scripts/check_magic_numbers.py` |
| Naive datetime | `python scripts/check_no_naive_datetime.py` |
| Import layering | `lint-imports` |
| Copyleft tripwire | `python scripts/check_gpl_tripwire.py` |

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
| **Double-counted information inflating confidence** | KT-45 confidence-bound test | **KR-43** information-family correlation guard |
| **Unscoreable model** (no outcomes to compute IC) | `outcomes` row count | **T-001 is a hard prerequisite** (§8) |

---

## 11. Explicit non-goals

1. **Not** cloning, vendoring, or pip-installing Kronos as a runtime dependency
   of `aimos/` — Option B (§3.2) is an explicit, operator-actionable exception:
   the *weights* can be fetched and added by the operator; the *inference code*
   still runs out-of-process, never imported into `aimos/`.
2. **Not** having the trading runtime **fetch** Hugging Face weights at boot —
   this is an architectural choice (no network dependency on the hot path), not
   a statement that the weights are unreachable. If Option B is pursued, the
   operator downloads them once, ahead of time, outside the runtime (§3.2).
3. **Not** adding torch to the **trading runtime process** (KR-10) — an
   out-of-process Kronos microservice (§3.2 step 4) may use torch; it just never
   shares a process, dependency graph, or memory budget with `aimos`.
4. **Not** adding a 4th `EngineOpinion` engine (C2).
5. **Not** letting execution plugins consume forecasts (route K).
6. **Not** auto-promoting the model to nonzero influence (KR-31).
7. **Not** changing the live-order path in any way (KR-35).
8. **Not** re-implementing Kronos's cost-free backtest posture (KR-36).

---

## 12. Open questions for the operator

### 12.1 Actions only the operator can take (this session is network-restricted to these hosts)

Consolidated in one place — full detail and exact commands in
**`specs/OPERATOR_ACTIONS.md`**:

- Run `scripts/download_history.py` (T-003 step 1 — `data.binance.vision` is
  403-blocked from this development sandbox).
- If Option B (§3.2) is wanted: download Kronos weights from Hugging Face and add
  them to the repo (`huggingface.co` is likewise 403-blocked here).

### 12.2 Decisions

1. **Registry approval (KR-23).** Approve the four evidence names? Adding them
   invalidates existing trained `LogisticModel` artifacts and forces a retrain.
   Note KR-43's corollary: if you want to approve fewer, **`forecast_band` is the
   one to keep** — it is the only genuinely new information.
2. **Measurement loop (T-001).** Confirm the sequencing: close the outcomes loop
   before K1. Without it the K2 gate is unevaluable and the model is unscoreable.
3. **Training data (T-003).** The 12-month dataset is still *not built* per
   `specs/STATUS.md`. K1 needs `scripts/download_history.py` run first.
4. **Timeframe scope.** Start with `15m`+`1h` only? 1m multiplies cost by ~15× for
   the noisiest, least forecastable horizon.
5. **Universe scope.** Majors only at K2, or the full tiered universe?
6. **Deployment target.** Is the 4 GB host the Coolify deploy? If so, confirm the
   headroom after TimescaleDB and the API process.
7. **Model-size ceiling (KR-5).** Confirm 8M params as the hard cap that CI
   enforces.

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

**But the sequencing matters more than the build.** A forecaster is an instrument,
and AIMOS currently has no way to read any instrument: 2,760 decisions, zero
outcomes, nothing ever scored. Adding a new sensor to a system that cannot measure
its existing thirteen would add a second unknown on top of the first.

Close the loop (T-001), get the costed backtest (T-003), find out whether the
strategies you already have carry edge. Then build this — and you will be able to
tell, in numbers rather than argument, whether it earns its 0.35.
