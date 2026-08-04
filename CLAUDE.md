# CLAUDE.md — working rules for this repo

You are working on **AIMOS**, a deterministic crypto trading system. Read this
before doing anything.

## Before you start (every task)

1. Read **`specs/STATUS.md`** — what's built, what's dormant, what's next.
2. Read **`CHANGELOG.md`** (top) — the most recent work.
3. For design/behavior questions, consult **`specs/ARCHITECTURE.md`** (the build
   contract; sections are referenced as §N throughout the code).
4. For run/deploy/config questions, consult **`specs/OPERATIONS.md`**.

Do not re-implement something that STATUS marks ✅. Do not "enable" something
marked 🟡 without providing its prerequisite. Pick the next ⏭️ item unless told
otherwise.

## After you finish (every change)

1. **Update `CHANGELOG.md`** — add an entry under *Unreleased* describing what you
   did (one line per meaningful unit). This is mandatory.
2. **Update `specs/STATUS.md`** if the build state changed (moved an item between
   ✅ / 🟡 / ⏭️, added a screen/endpoint/module).
3. Update `specs/OPERATIONS.md` if you added a flag, env var, or run mode.
4. Run and pass: `python -m pytest`, `python scripts/check_magic_numbers.py`,
   `python scripts/check_no_naive_datetime.py`, `lint-imports`.

## Hard rules (never violate)

- **Layering:** `observation → intelligence → execution` talk only via pydantic
  contracts; import direction is enforced by import-linter. Don't add cross-layer
  imports.
- **No LLM in the decision path** (§15.3). The LLM is a sensor/explainer only.
- **No hardcoded tunables** in `aimos/observation/`, `aimos/intelligence/`,
  `aimos/execution/` — the magic-number lint scans these. Route values through
  config or `aimos/core/normalize` constants; `# noqa: magic` only for genuine
  structural/unit constants.
- **All time via `clock.now()`** — never `datetime.now()` in library code.
- **Never edit `aimos/core/schemas.py` or the evidence registry** without explicit
  human approval.
- **No copyleft (GPL/AGPL) package is imported into `aimos/`** — if a capability is
  wanted, it runs as an isolated out-of-process service called over its API
  (§21.1/§22.3 rule 5).
- **Live trading stays fail-closed:** mandate + go-live ladder + boot guard. Never
  add a path that reaches live orders without those gates.
- Secrets are never logged, journaled, or returned to the UI.

## Conventions

- Config over constants (`config/*.yaml`, env override `AIMOS__SECTION__KEY`).
- New execution strategy = one plugin file + a `config/plugins/<name>.yaml`; the
  evaluator needs no changes.
- Tests live beside the feature and must be green before you call it done.
- Match the surrounding code's style, comment density, and naming.
