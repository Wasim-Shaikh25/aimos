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

Items are ordered by what unblocks the most downstream work.

---

## 1. Download 12-month exchange history (unblocks T-003, and everything downstream of it)

**Verified blocked from this session:**
```
$ curl https://data.binance.vision
CONNECT tunnel failed, response 403
```

**What to run**, anywhere with normal internet access:
```bash
python scripts/download_history.py
```
Writes candle data to the path configured under `storage` in `config/default.yaml`
(Parquet by default). Binance publishes free historical klines at
`data.binance.vision` — no API key needed.

**Then:**
```bash
python scripts/dataset_integrity.py
```
to verify the download before anything else touches it.

**Unblocks:** `specs/TASKS.md` **T-003** (the costed backtest — the single
highest-leverage task in the whole backlog, per `specs/STATUS.md`), and
transitively **T-010** (config fitting), **K1** (Kronos forecaster training,
`specs/KRONOS_INTEGRATION.md`), and every "does any strategy have edge" question
raised in this project so far.

**Status:** ⬜ not done.

---

## 2. (Optional) Kronos real pretrained weights — only if Option B is wanted

**Verified blocked from this session:**
```
$ curl https://huggingface.co
CONNECT tunnel failed, response 403
$ pip install huggingface_hub
Would install ... huggingface_hub-1.27.0    ← the PACKAGE installs fine; only
                                                fetching from huggingface.co itself
                                                is blocked here
```

**Not required by default.** `specs/KRONOS_INTEGRATION.md` recommends **Option
A** — an AIMOS-native clean-room model, smaller than even Kronos's own smallest
checkpoint, trained on your actual crypto history once item 1 above is done. That
recommendation holds regardless of whether these weights are ever fetched (see
`specs/KRONOS_INTEGRATION.md` §3.1 — the reasons are about market fit,
determinism, and process isolation, not network access).

**If you want to try the real model anyway** (e.g. to compare against Option A
before committing), full steps are in `specs/KRONOS_INTEGRATION.md` §3.2. Short
version:

```bash
pip install huggingface_hub
huggingface-cli download NeoQuasar/Kronos-Tokenizer-base --local-dir kronos_weights/tokenizer
huggingface-cli download NeoQuasar/Kronos-small --local-dir kronos_weights/model
```

Then add the downloaded files to the repo under a new `vendor/kronos_weights/`
path with a `vendor/manifest.yaml` entry (recording the exact HF revision), and
tell me — I'll wire the out-of-process `ForecastProvider` adapter (KR-39), the
inference-only dependency extra, and a harness to compare it against Option A on
identical, costed terms.

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
