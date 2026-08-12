# OPERATOR_ACTIONS — everything that needs your hands, not mine

**Why this file exists.** This development session runs in a sandboxed container
with a restricted egress policy — some hosts return a 403 at the network level,
confirmed directly rather than assumed (see each item below). That restriction is
**specific to this session**, not to AIMOS, not to any architectural decision, and
almost certainly not to your own machine, CI runner, or deploy target.

An earlier pass folded "I can't reach this host" into "this shouldn't be done" in
two places (`specs/KRONOS_INTEGRATION.md`, `specs/TASKS.md` T-003) without saying
so — that was wrong, and is fixed at each source. This file exists so it never
happens silently again: **every time something is skipped, deferred, or narrowed
because of this session's network access, it is logged here with the exact
command to run and where the output goes.**

Nothing on this list is a permanent limitation of AIMOS. Everything on it is a
command you (or CI, or the production host) can run today.

---

## How to use this file

1. Pick an item.
2. Run the command in an environment with normal internet access.
3. Report back (or just push the result / place the file where indicated).
4. Tell me it's done — the follow-on work (steps that depend on the fetched data)
   picks up from there in the same or a new session.

Items are ordered by what unblocks the most downstream work — that's a measure of
leverage, not a required sequence. The operator can and has picked a different
order (item 2 first, as of 2026-08); each item's **Status** line reflects actual
progress, independent of its position in the list.

---

## 1. Download 12-month exchange history (unblocks T-003, and everything downstream of it)

**Verified blocked from this session:**
```
$ curl https://data.binance.vision
CONNECT tunnel failed, response 403
```

**What to run**, anywhere with normal internet access:
```bash
# all currently trading non-stable USDT spot pairs, 1h, 12 months
python -m scripts.download_history --all --timeframe 1h --months 12

# or a top-N subset (e.g., top 100 by 24h quote volume)
python -m scripts.download_history --all --top-n 100 --timeframe 1h --months 12

python -m scripts.dataset_integrity
```
Writes candle data to the path configured under `storage` in `config/default.yaml`
(Parquet by default). Binance publishes free historical klines at
`data.binance.vision` — no API key needed.

The `--all` flag is new; it fetches the symbol list from `www.binance.com/api/v3`,
excludes stablecoin bases by default, and downloads all remaining pairs concurrently.

**Unblocks:** `specs/TASKS.md` **T-003** (the costed backtest — the single
highest-leverage task in the whole backlog, per `specs/STATUS.md`), and
transitively **T-010** (config fitting), **K1** (Kronos forecaster training,
`specs/KRONOS_INTEGRATION.md`), and every "does any strategy have edge" question
raised in this project so far.

**Status:** 🟨 **ready to run** — `scripts/download_history.py` now supports `--all`
and bounded concurrency; the 12-month download is no longer blocked by missing
code. The operator still needs to run it where `data.binance.vision` is reachable
and then re-run the T-003 backtest with the full dataset if they want a complete
universes card (current run cards are Tier-1 only).

Note this means K1 (training AIMOS's own native forecaster on real data) is also
on hold until the full history lands, independent of how item 2 goes.

---

## 2. Kronos real pretrained weights — operator is doing this now (Option B)

**Status:** 🟨 **in progress** — operator has chosen to pursue this before item 1.
Exact download/placement steps and the mini-vs-small sizing decision are fully
specified in `specs/KRONOS_INTEGRATION.md` §3.2 (not duplicated here to avoid two
copies drifting) — this entry tracks the network-access finding only.

**Verified blocked from this session:**
```
$ curl https://huggingface.co
CONNECT tunnel failed, response 403
$ curl https://download.pytorch.org
CONNECT tunnel failed, response 403        ← the CPU-only torch wheel lives here
$ pip download torch                        (default PyPI index, CUDA-bundled)
Downloaded torch-2.13.0-...-x86_64.whl (526.6 MB)   ← real, measured this session;
                                                        confirms why the CPU-only
                                                        wheel from the blocked host
                                                        above matters — see §3.2
$ pip install huggingface_hub
Would install ... huggingface_hub-1.27.0    ← the PACKAGE installs fine; only
                                                fetching from huggingface.co itself
                                                is blocked here
```

**Worth restating even though this is now underway:** `specs/KRONOS_INTEGRATION.md`
§3.1 still recommends **Option A** (AIMOS-native clean-room model) as the
architectural default — those reasons are about market fit, determinism, and
process isolation, and none of them change once the weights exist locally.
Option B doesn't replace that recommendation; it runs *alongside* it, out-of-
process (KR-39), so both can be measured on identical, costed terms once item 1
provides real data to measure against.

**Final recommendation, with reasoning:** `Kronos-small` + `Kronos-Tokenizer-base`,
not `Kronos-mini` — full sizing table and rationale in §3.2. Short version: once
torch is loaded at all, its own runtime overhead dwarfs the difference between an
~8 MB and an ~99 MB weight file, and `Kronos-small` matches the context length
(90–512 bars) upstream actually finetunes and evaluates with, per their own
`finetune/config.py` (§2.0.2) — `Kronos-mini`'s extra context (2048) buys nothing
we'd use.

```bash
pip install huggingface_hub
huggingface-cli download NeoQuasar/Kronos-Tokenizer-base --local-dir kronos_weights/tokenizer
huggingface-cli download NeoQuasar/Kronos-small --local-dir kronos_weights/model

# CPU-only torch — NOT plain `pip install torch` (that pulls the 526.6 MB
# CUDA-bundled default wheel, verified above; this needs the blocked host too,
# so run this from wherever you're running the other commands)
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Then add the downloaded files to the repo under `vendor/kronos_weights/` with the
exact `vendor/manifest.yaml` stanza given in `specs/KRONOS_INTEGRATION.md` §3.2
step 2, and tell me — I'll wire the out-of-process `ForecastProvider` adapter
(KR-39), the microservice Dockerfile, the `[kronos]` `pyproject.toml` extra, and
the comparison harness against Option A.

**Unblocks:** nothing else is gated on this — it's a genuine option, not a
prerequisite. Item 1 (history data) is still needed either way, to score either
model against reality.

**Status:** ⬜ not done, not currently recommended as the default path (Option A
is), available whenever wanted.

---

## 3. Exchange testnet keys (already correctly documented — listed here for completeness)

Already has its own operator runbook: **`specs/TESTNET.md`**, §1, *"Get Binance
testnet keys (5 minutes, free)."* Free, requires only a Binance account, takes
about five minutes. Not re-documented here — follow that file directly.

**Unblocks:** `specs/TASKS.md` **N-01** (real-exchange testnet validation),
`scripts/testnet_order.py`, and the `testnet_1wk` go-live gate
(`aimos/runtime/golive.py`).

**Status:** ⬜ not done (per `specs/TESTNET.md`'s own tracking).

---

## 4. Anything else this session finds it can't reach

This file is a living list, not a one-time snapshot. If a future task needs
something outside this session's egress allowlist, the rule is: **name the
blocked host, show the actual failure (not an assumption), state precisely what
still holds true regardless of access, and add an entry here with the exact
command** — never silently narrow scope or drop a capability because of where
this conversation happens to be running.

---

## What is *not* on this list, on purpose

To be equally explicit about the other direction: most of this project's research
did **not** require operator action. GitHub raw source (used throughout
`specs/COMPETITIVE_ANALYSIS.md` and `specs/KRONOS_INTEGRATION.md`'s architecture
citations), PyPI package metadata, and this repository's own git history are all
reachable from this session without restriction. The two items above are the only
ones found — narrow, not a pattern, but tracked precisely because they're rare
enough to otherwise get missed.
