# AIMOS — AI Market Operating System

Autonomous crypto market-intelligence and trading system. Three deterministic layers — **Observation → Intelligence → Execution** — plus learning, agents, and institutional-grade risk controls. Stablecoin-quoted pairs only. Private project.

## Document map

| File | Purpose |
|---|---|
| `AIMOS_Implementation_Plan.md` | **The build contract (v2.1).** Every module: logic, formulas, thresholds, schemas, tests. Sections referenced everywhere as §N. |
| `BUILD_TASKS.md` | **Phase-by-phase task cards** for Cursor Composer. Execute in order. |
| `README.md` | This file — how to operate the build. |

## Non-negotiable architecture rules (repeat these to the agent every session)

1. Layers communicate ONLY through pydantic contracts (§3, §25.1). Observation never signals; Intelligence never orders; Execution never reads raw candles.
2. `NO_TRADE` is always a valid, first-class decision.
3. No LLM in the decision path (§15.3). LLM allowed only as news sensor (§19), explainer, and research agents.
4. Zero hardcoded tunables — everything in `config/*.yaml` (§23.12). CI lint enforces.
5. Every decision journaled with reasons; journal is hash-chained (§24.5).
6. All timestamps UTC; all time via `clock.now()` (§4.5) — never `datetime.utcnow()` in modules.
7. Import direction: `observation → intelligence → execution` only, enforced by import-linter. Nothing imports `vendor/vt_research` (§22.3).
8. Any spec gap → `# SPEC-GAP:` comment + simplest compliant choice. Never invent features.

## How to drive Cursor Composer (per §25.10)

**Session workflow:**
1. Open a session scoped to ONE task card (or one small group sharing a package).
2. Paste the prompt template below with the card ID.
3. Agent implements → runs the card's DoD tests → you review the diff.
4. Green tests + clean import-linter = card done. Check it off in `BUILD_TASKS.md`. **Never start a card whose dependencies aren't done. Never proceed on red.**

**Prompt template:**
```
You are implementing AIMOS. Read these before writing code:
- AIMOS_Implementation_Plan.md sections: <card's spec refs> plus §3 and §25
- BUILD_TASKS.md card <ID>
Rules: follow the spec exactly; all tunables from config; mark any ambiguity
with # SPEC-GAP and pick the simplest compliant option; do not add features;
write the tests listed in the card's DoD and make them pass.
Implement card <ID> now.
```

**Phase gates:** at the end of each phase, run the whole phase's test suite plus all previous phases' suites. Phase 3+ must also pass the golden integration test (§25.9) byte-for-byte to ±0.01.

**Parallelism:** cards marked `∥` are independent within their phase — you can run them in separate Composer sessions/worktrees simultaneously (contracts in §3/§25 are the interface). Cards touching `core/schemas.py` are never parallel and never delegated without review.

## Runtime layout (target)

```
docker compose up  →  trading runtime · research service · dashboard · postgres · telegram bot · watchdog
```

Paper mode is the default everywhere. Live mode requires the §23.8 go-live gate ladder, `mandate.yaml`, and withdrawal-disabled API keys (§23.4) — the code refuses otherwise.

## Status tracking

Mark cards in `BUILD_TASKS.md`: `[ ]` todo · `[~]` in progress · `[x]` done (tests green). Keep a one-line note per completed card: date + any SPEC-GAP decisions made, so the plan document can be amended later.
