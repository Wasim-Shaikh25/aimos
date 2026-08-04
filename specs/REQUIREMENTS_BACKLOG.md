# Requirements Backlog — outstanding work to make AIMOS more robust

**Purpose:** one durable list of everything identified as worth building next, from
two sources: (1) residual items in `PRODUCTION_READINESS_AUDIT.md` after the C1/C2/
H1–H5/M8 remediation pass, and (2) a competitive-feature review against
TradingAgents (Tauric Research) and the OpenBB Platform.

This is a **backlog, not a status report** — `specs/STATUS.md` stays the terse
current-state pointer; each item here has enough context (evidence, acceptance
criteria, priority) to pick up cold. Nothing in this document is built yet unless
its checkbox says so. When an item ships: check it off here, move its summary into
`CHANGELOG.md` under *Unreleased*, and update `specs/STATUS.md`'s state if it
changed (✅/🟡/⏭️).

Legend: `[ ]` not started · `[x]` done (left in place briefly for continuity, then
removed once folded into STATUS.md).

---

## Tier 1 — finish what's already built (highest value, lowest effort)

### REQ-1: Wire `aimos/risk/analytics.py` to an API endpoint and the dashboard

- **Source:** competitive research (TradingAgents tracks "alpha vs. SPY"; AIMOS's
  own `specs/ARCHITECTURE.md` §24.3/§24.4 specifies the same thing against BTC + an
  equal-weight T1 basket, going further with VaR/ES and factor decomposition).
- **Evidence:** `alpha_beta()`, `historical_var_es()`, `factor_decomposition()` are
  implemented and tested (`tests/test_risk_analytics.py`) but are called from
  **nowhere** — no `/api/*` route, no scheduled job, no dashboard payload. The only
  UI trace is a placeholder string in `dashboard/src/screens/PositionsRisk.jsx`:
  *"renders when the risk-analytics daily job posts to /api/stress"* — that job and
  endpoint do not exist (verified by search across `serve.py`/`server.py`).
- **Rationale:** §24.4 frames this as "the number an investor actually buys" — of a
  quarter's return, how much is BTC-beta versus real alpha. The Performance screen
  today only shows realized PnL / win rate / drawdown, never answers that question.
  This is a finished capability sitting idle, not new scope.
- **Acceptance criteria:**
  - `GET /api/risk` (or `/api/stress`, matching the existing placeholder string)
    returns VaR/ES (95%/99%), the BTC-beta/idiosyncratic factor split, and
    alpha/beta with t-stat vs. both benchmarks (BTC, equal-weight T1 basket).
  - A daily job (APScheduler, matching the existing runtime pattern) computes and
    caches this so the endpoint doesn't recompute on every poll.
  - `PositionsRisk.jsx` renders the stress panel; `Performance.jsx` shows the
    alpha/beta split alongside existing PnL metrics.
  - Tests: an API test asserting the endpoint shape; a dashboard smoke test.
- **Priority:** High. **Effort:** Small (plumbing only — the math is done).
- **Dependencies:** none.

### REQ-2: Independent verification pass of the C1/C2/H1–H5/M8/H4/H5 fixes

- **Source:** `PRODUCTION_READINESS_AUDIT.md` → *Remediation Applied*.
- **Rationale:** every fix in that pass was authored and self-verified by the same
  actor in the same engagement. C1/C2 were verified against a live server; H1/H2/
  H3/M8/H4/H5 carry passing tests but have not been independently re-checked.
- **Acceptance criteria:** someone other than the fix author re-runs: the encoded-
  traversal matrix against a live server (C1), the SaaS-mode login journey in a
  browser (C2), a remote (non-loopback) call against `/api/control/*` (H1), the
  OTP/auth throttle from a real client (H3), and confirms `.github/workflows/ci.yml`
  goes green on an actual GitHub Actions run (H5). Findings move from *Fixed —
  Awaiting Verification* to *Verified* in the audit report only after this.
- **Priority:** High. **Effort:** Small (verification, not new code).
- **Dependencies:** none — can run today.

### REQ-3: Bound the `/api/decisions?limit=` query parameter

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M5.
- **Evidence:** `aimos/api/server.py` passes `limit` straight into a SQL `LIMIT ?`
  with no bound; `?limit=100000000` loads the entire journal into memory.
- **Acceptance criteria:** `limit: int = Query(50, ge=1, le=500)`; same bound applied
  to `_assistant_decisions` in `serve.py`.
- **Priority:** Medium. **Effort:** Trivial.
- **Dependencies:** none.

---

## Tier 2 — security/ops hardening

### REQ-4: Admin password change endpoint + UI (closes M2)

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M2.
- **Evidence:** `ensure_admin_user` re-hashes the password from config **on every
  boot** — the plaintext must live in `config/saas.yaml`/env permanently, and any
  out-of-band change is silently reverted on restart.
- **Acceptance criteria:** `POST /api/v2/me/password` (current password + new
  password, checked with the existing `is_strong_password` helper in
  `aimos/saas/security.py`, already present and unused since the M1 cleanup);
  `ensure_admin_user` seeds from config only when the user row doesn't exist yet;
  changing the password revokes all outstanding refresh tokens; a Settings UI
  section for it.
- **Priority:** Medium. **Effort:** Small.
- **Dependencies:** none.

### REQ-5: Stop swallowing admin-seed failures; add an auth audit log

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M4.
- **Evidence:** `aimos/saas/db.py` wraps `ensure_admin_user` in a bare
  `except Exception: pass` — a seeding failure boots the app successfully with no
  admin account and no diagnostic. There is also no log event for login success/
  failure, refresh, logout, or exchange-key changes, despite the pattern already
  existing for trading controls (journaled with `source="ui"`).
- **Acceptance criteria:** log and re-raise on admin-seed failure when
  `saas.enabled` is true (fatal misconfiguration, not a degrade); structured log
  events for the auth lifecycle (login attempt, OTP verify, refresh, logout,
  exchange-key add/remove).
- **Priority:** Medium. **Effort:** Small.
- **Dependencies:** none.

### REQ-6: `/healthz` and `/readyz` endpoints

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M6 / gap G4.
- **Evidence:** `docker-compose.yml` has `restart: unless-stopped` and a watchdog
  service, but nothing distinguishes "process up" from "trading loop alive" over
  HTTP — the watchdog's heartbeat file isn't exposed.
- **Acceptance criteria:** `GET /healthz` (liveness — process responds, public, no
  auth) and `GET /readyz` (readiness — journal writable, loop heartbeat fresher
  than N seconds); wired into `docker-compose.yml`'s healthcheck.
- **Priority:** Medium. **Effort:** Small.
- **Dependencies:** should be public even when `saas.enabled` — extend
  `_is_public_path` in `aimos/api/server.py` (the same allow-list from the C2 fix).

### REQ-7: Alert on repeated failed logins

- **Source:** `PRODUCTION_READINESS_AUDIT.md` gaps G3/G7.
- **Rationale:** the H3 throttle bounds brute force but produces no signal to the
  operator; Telegram alerting already exists for trading events.
- **Acceptance criteria:** N failed `/auth/login` or `/auth/login/verify` attempts
  within a window triggers a Telegram alert (reuses the existing bot/notifier).
- **Priority:** Low-Medium. **Effort:** Small.
- **Dependencies:** REQ-5 (auth log events are the natural trigger source).

### REQ-8: Sequential go-live gate prerequisites

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding L3.
- **Evidence:** `GoLiveLadder.mark()` validates only that a gate ID exists —
  `scaling` can be marked before `backtest_validated`. Doesn't weaken the
  fail-closed guarantee (still requires *all* gates), but can misrepresent
  sequence in the UI.
- **Acceptance criteria:** `mark()` rejects out-of-order sign-off, or the UI
  visibly flags it.
- **Priority:** Low. **Effort:** Trivial.
- **Dependencies:** none.

### REQ-9: Adopt a migration framework for the auth/settings DB

- **Source:** `PRODUCTION_READINESS_AUDIT.md` Remediation Plan, Group 4.
- **Rationale:** `aimos/saas/db.py` uses `Base.metadata.create_all`, which cannot
  alter existing tables. H3 already needed a manual `EmailLoginCode.attempts`
  column; every future schema change hits this. On an existing deployment that
  table currently needs to be dropped by hand for the column to appear.
- **Acceptance criteria:** Alembic (or equivalent) wired to `aimos/saas/models.py`;
  a baseline migration; the H3 column becomes a proper migration.
- **Priority:** Medium (compounds if deferred). **Effort:** Medium.
- **Dependencies:** none, but do this before the next auth-DB schema change.

---

## Tier 3 — product decisions (not code — need an answer, then possibly code)

### REQ-10 / PD1: Network-exposure model

- **Question:** is AIMOS ever reachable beyond localhost / an authenticated
  reverse proxy?
- **Why it matters:** finalizes finding H1's disposition. The current fix
  (loopback-default host + loopback-only control endpoints when SaaS is off)
  closes accidental and anonymous-remote exposure; whether that's sufficient or
  whether a proxy/VPN requirement should be documented as mandatory depends on
  this answer.
- **Output:** a decision recorded in `specs/OPERATIONS.md`.

### REQ-11 / PD3: Copyleft dependency policy (GPL/AGPL)

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M7, sharpened by today's
  OpenBB research.
- **Finding:** `scripts/check_gpl_tripwire.py` already guards two GPL-origin files
  (private-use-only). Today's research surfaced the same risk class from a
  different angle: **OpenBB Platform is AGPLv3** — the network-use clause means
  importing it directly into the `aimos` package (a network-exposed service) would
  very plausibly require the whole connected codebase to go AGPL. The project
  already has the right isolation pattern for this (`services/research`, firewalled
  by an import-linter contract forbidding `vendor.vt_research` in the runtime) — it
  just isn't written down as a standing rule for *future* dependency choices.
- **Question:** formalize "no copyleft (GPL/AGPL) package is ever imported into
  `aimos/`; if its capability is wanted, it runs as an isolated out-of-process
  service called over its API, same as `services/research`" as an explicit rule in
  `CLAUDE.md` / `specs/ARCHITECTURE.md`? (Recommend yes — costs nothing, prevents a
  real recurring risk.)
- **Output:** a written rule, and optionally extending `check_gpl_tripwire.py` to
  flag AGPL in `pyproject.toml` dependency pins, not just tracked source files.

### REQ-12 / PD5: Backup schedule (RPO/RTO target)

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding H4 (script built, not
  scheduled).
- **Question:** what RPO (max acceptable data loss) and RTO (max acceptable
  downtime) for the journal? Determines the cron/timer interval for
  `scripts/backup_journal.py` and the `--keep` retention value.
- **Output:** a cron entry / compose timer / APScheduler job at the chosen
  interval, documented in `specs/OPERATIONS.md`.

---

## Tier 4 — longer-term architecture

### REQ-13: Separate the API process from the trading loop

- **Source:** `PRODUCTION_READINESS_AUDIT.md` Remediation Plan, Group 4.
- **Rationale:** H3's CPU-exhaustion impact (bcrypt work starving the decision
  loop) exists *because* `runtime/serve.py` runs both the HTTP API and the trading
  loop in one process. Splitting them converts a trading outage into a UI outage.
- **Priority:** Low (structural; the H3 throttle already bounds the immediate
  risk). **Effort:** Large.

### REQ-14: Move key material outside the working-directory subtree

- **Source:** `PRODUCTION_READINESS_AUDIT.md` Remediation Plan, Group 4 — the
  structural fix for the bug class C1 was in (not just the one instance).
- **Acceptance criteria:** `state/.jwt_secret`, `state/.settings_key` resolvable
  from a path outside `dashboard/dist`'s ancestry by default, or documented as
  required to live on a separate volume in the Docker deployment.
- **Priority:** Low (C1 itself is fixed; this is defense in depth). **Effort:**
  Medium.

### REQ-15: Full browser-driven accessibility audit

- **Source:** `PRODUCTION_READINESS_AUDIT.md` Residual Risks — only an automated
  Chromium probe has run (0 unlabeled inputs/buttons found; 1 real defect,
  `<html lang>`, already fixed).
- **Acceptance criteria:** keyboard-only traversal, focus-visible states, colour
  contrast on the badge/status colours, and screen-reader flow checked across all
  21 dashboard screens.
- **Priority:** Low-Medium. **Effort:** Medium.

### REQ-16: Build a real `OnchainProvider` to un-gate the on-chain engine

- **Source:** `specs/STATUS.md` dormant list, sharpened by today's OpenBB research.
- **Evidence:** `aimos/observation/onchain_engine.py` is real, tested, dormant code
  — it wants `active_addresses` and `stablecoin_inflow` time series and returns `[]`
  with no provider configured.
- **Path:** a direct connector to a specific on-chain data API (Glassnode, Nansen,
  Dune, etc.), **or** — if OpenBB's aggregation is specifically wanted — call it as
  an isolated out-of-process service per REQ-11's rule, never imported into
  `aimos/`.
- **Priority:** Low (new scope, not a defect). **Effort:** Medium.
- **Dependencies:** REQ-11 (copyleft policy) if OpenBB is the chosen path.

### REQ-17: Refresh token to `httpOnly` cookie + CSP headers

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding M3.
- **Note:** exploitability is now low — Pass 2 confirmed zero `dangerouslySetInnerHTML`/
  `innerHTML`/`eval` anywhere in `dashboard/src`, so the realistic XSS injection
  path doesn't exist today. This remains good hardening, not an active risk.
- **Acceptance criteria:** refresh token moved to `httpOnly; Secure; SameSite=Strict`
  cookie; access token kept in memory only; a `Content-Security-Policy` response
  header added.
- **Priority:** Low. **Effort:** Small.

### REQ-18: Dummy bcrypt comparison on the login not-found path

- **Source:** `PRODUCTION_READINESS_AUDIT.md` finding L4 (accepted risk).
- **Note:** low value target — one known admin account, not a discoverable user
  list. Optional hardening only.
- **Priority:** Low. **Effort:** Trivial.

### REQ-19: Explanation-only "case for / case against" narrative in the AI Analyst

- **Source:** competitive research (TradingAgents' bull/bear researcher debate
  pattern).
- **Constraint:** must remain **pure explanation of an already-made deterministic
  decision** — CLAUDE.md's hard rule (§15.3, no LLM in the decision path) is
  non-negotiable and this must not become a second decision input.
- **Acceptance criteria:** `/api/assistant` (or `/report`) can optionally generate
  a two-sided narrative — the case for and against a completed decision — sourced
  from the same journal grounding the analyst already uses, clearly labeled as
  post-hoc explanation.
- **Priority:** Low (nice-to-have UX, not a gap). **Effort:** Small.

---

## Explicitly not on this list

- **TradingAgents' core architecture** (LLM agents drive the trade decision) — not
  adopted. Directly conflicts with the no-LLM-in-decision-path hard rule; this is
  an architectural boundary, not a missing feature.
- **OpenBB's equities/options/fixed-income data** — out of scope; AIMOS trades
  stablecoin-quoted crypto pairs only, by design.
- **OpenBB Workspace / Excel integration** — audited separately as G6 (data
  export), classified Improvement Opportunity, not required for a single-operator
  tool with a directly-queryable journal.
