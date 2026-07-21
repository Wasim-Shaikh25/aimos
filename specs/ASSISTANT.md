# ASSISTANT — the read-only AI analyst

**Objective:** a natural-language analyst you can ask anything about the running
system — why a decision was made, how a timeframe performed, whether the ML is
working, whether to paper-trade more or disable a method — answered from the
**journal and real metrics**, never from vibes. Exposed on the dashboard (chat
window) and Telegram (`/ask`, `/report`).

This is the **sanctioned** role for AI in AIMOS (§15.3): the LLM is a
sensor/explainer, never in the decision path. The analyst reads state and
*advises you*; it cannot place trades, flip flags, or edit config.

## Hard guardrails (non-negotiable)

1. **Read-only.** The analyst only *reads* providers + the journal. It has no
   ability to mutate anything. Any action it recommends is executed by **you**
   through the existing CONFIRM-gated controls (UI / Telegram nonce).
2. **Grounded, not freelancing.** Every answer is built from a JSON evidence
   bundle assembled from the journal + metrics. The prompt forbids inventing
   numbers and asks it to cite decision_ids / figures. If the data doesn't
   answer, it must say so.
3. **Secrets never enter the prompt.** The journal and providers already exclude
   secrets; the grounding bundle is built only from them.
4. **Explainer, not oracle.** It shows its numbers; you verify. It is advisory.
5. **Off by default.** Needs `assistant.enabled: true` **and** `ANTHROPIC_API_KEY`.
   On-demand only (you ask) — never called per tick.

## Architecture

```
providers (read-only) ──► build_grounding() ──► JSON evidence bundle
                                                      │
   your question ──────────────────────────────────► LLM (Anthropic, httpx)
                                                      │
                                                grounded answer (cited)
```

- **`aimos/runtime/assistant.py`** — `build_grounding(providers, timeframe=None)`
  assembles a compact, JSON-serializable snapshot: recent decisions (id, symbol,
  regime, action, plugin, p_up, confidence, reasons), performance metrics,
  model/ML status (rule/bayes/ml + fusion weights + whether a model is loaded),
  the monitor coverage report, feature flags, go-live progress, and the equity
  summary. `Assistant.answer(question)` and `Assistant.report(timeframe)` call the
  LLM with a strict read-only analyst system prompt. The LLM caller is an
  **injected callable** (plain httpx POST to the Anthropic Messages API), so the
  whole thing is testable with no network.
- **API:** `POST /api/assistant {question}` and `GET /api/assistant/report?timeframe=24h`.
  Return 503 when disabled/no key. Read-only — no CONFIRM needed.
- **Telegram:** `/ask <question>`, `/report <timeframe>` (read-only info commands).
- **UI:** an **Assistant** dashboard screen — chat window + a report button.

## What it can answer well

- "Why did we NO_TRADE SOL at 14:00?" → cites the journaled decision + reasons.
- "How did the last 24h go?" → grounded performance + health report.
- "Is the ML working?" → shadow AUC, whether a model is loaded, fusion weight,
  Brier/drift if present — with the honest caveat that weight 0 = not yet trusted.
- "Which strategy is pulling its weight?" → per-strategy chosen counts + PnL, with
  sample-size caveats.
- "Should we paper-trade more / train more on history / disable X?" → advice keyed
  to sample counts, gate status, and per-strategy stats. **Advisory only.**

## What it deliberately does NOT do

- Place trades, flip features, or write config (read-only, by design).
- Deep code auditing at runtime — that's a dev-time job for a coding agent. The
  analyst answers *operational/behavioral* questions about the running system.
- Claim profitability it can't support — backtest/paper numbers are not a live
  edge, and the prompt says so.

## Config (`config/default.yaml assistant:`)

| Key | Default | Meaning |
|---|---|---|
| `assistant.enabled` | `false` | master switch (env `AIMOS__ASSISTANT__ENABLED=true`) |
| `assistant.provider` | `anthropic` | LLM backend: `anthropic` or `openai` |
| `assistant.model` | `claude-sonnet-5` | Anthropic model id (provider: anthropic) |
| `assistant.openai_model` | `gpt-4o-mini` | OpenAI model id (provider: openai; cheap) |
| `assistant.max_tokens` | `1200` | response cap |
| `assistant.temperature` | `0.2` | low — analysis, not creativity |
| `assistant.recent_decisions` | `40` | decisions pulled into the grounding bundle |
| `assistant.timeout_seconds` | `40` | LLM call timeout |

Enable (Anthropic): `export ANTHROPIC_API_KEY=…` then `AIMOS__ASSISTANT__ENABLED=true`.
Enable (OpenAI, cheaper): `export OPENAI_API_KEY=…`,
`AIMOS__ASSISTANT__PROVIDER=openai`, `AIMOS__ASSISTANT__ENABLED=true`. Both backends
use the same grounded, read-only prompt — only the API differs. The caller is
injectable, so both are covered by offline tests.
