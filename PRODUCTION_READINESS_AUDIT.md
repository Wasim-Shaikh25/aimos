# AIMOS — End-to-End Production Readiness Audit

**Audit date:** 2026-07-30
**Commit audited:** `5fd1b88` (branch `claude/new-session-f5fp2i`)
**Auditor scope:** cross-functional review — engineering, application security, QA,
SRE/DevOps, data architecture, product, UX/accessibility, performance.
**Authorization:** audit-only. **No application source code was modified.** All
findings below are reported, not fixed.
**Passes:** Pass 1 (static + targeted execution) and Pass 2 (live-server execution
— dashboard built and rendered in a real browser; C1 kill chain proven end to end;
new state-durability and accessibility findings). Pass 2 found **zero new Critical
or High** findings — see the *Pass 2 Addendum* below.
**Remediation:** a fix pass was subsequently **authorized and applied** on this
branch for **all seven Critical/High/Medium blockers** (C1, C2, H1–H5, M8) plus L5
— see *Remediation Applied* below. The Criticals are verified against a live server;
the Highs carry passing tests and await an independent verification pass. The
recommendation accordingly moves from **CONTINUE — NO-GO** to **STOP — CONDITIONAL
GO**, conditional on independent verification and the product decisions PD1–PD5.

---

## Executive Summary

AIMOS is a deterministic, single-operator crypto trading system. The **trading
core is in genuinely good shape**: the three-layer architecture is enforced
mechanically, the decision path is deterministic and free of hardcoded tunables,
the audit journal is SHA-256 hash-chained, and live trading is fail-closed behind
three independent locks. All four documented quality gates pass, and 466 tests are
green. That work is real and it holds up under inspection.

The problem is the **control plane wrapped around it** — the HTTP API, the
dashboard, and the authentication layer added most recently. Two independent
Critical defects were confirmed by execution, and together they mean:

> **There is currently no configuration in which the AIMOS dashboard is both
> reachable and authenticated.** With `saas_enabled: false` (the default) the
> trading control API has no authentication at all. With `saas_enabled: true` the
> dashboard — including its own login page — returns 401 and cannot be loaded.

Layered on top of that, an unauthenticated path-traversal bug in the SPA route
serves arbitrary files, including the JWT signing key, the settings encryption key,
and the plaintext 2FA codes. An attacker who can reach the port can forge admin
tokens outright; authentication is not merely bypassable, it is defeatable at the
root.

### Finding count by severity

| Severity | Count | Open blockers (post-remediation) |
|---|---|---|
| Critical | 2 | **0** — C1, C2 fixed & verified live |
| High | 5 | **0** — H1–H5 fixed (awaiting independent verification) |
| Medium | 8 | 0 (M8 fixed; rest pre-/post-release) |
| Low | 5 | 0 (L5 fixed) |
| **Total** | **20** | **0** |

*(Pass 2 added M8 and L5, with no new Critical/High. The remediation pass then fixed
**all seven Critical/High/Medium blockers** (C1, C2, H1–H5, M8) plus L5 — see
*Remediation Applied*. The Criticals are verified against a live server; the Highs
carry passing tests and await an independent verification pass. No release-blocking
finding remains open; what is left is product decisions PD1–PD5 and scheduled
Medium/Low items.)*

### Major technical risks

1. **Unauthenticated arbitrary file read** (C1) — leaks `state/.jwt_secret`,
   `state/.settings_key`, `state/maildrop/*`, `secrets.yaml`, `.env`. Proven by
   execution against a replica of the real directory layout.
2. **Authentication cannot be switched on** (C2) — enabling it 401s the UI,
   forcing every real deployment to run with the API fully open.
3. **No inbound rate limiting or lockout anywhere** (H3) — unbounded password and
   OTP guessing, plus an unauthenticated CPU-exhaustion vector against the same
   process that runs the trading loop.
4. **2FA codes persisted in plaintext and logged by default** (H2) — which, chained
   with C1, defeats the second factor.
5. **No backups exist and the restore drill reports success when none are found**
   (H4) — for a SQLite file that the README calls "the system of record."
6. **No CI/CD** (H5) — the four quality gates are documented and passing, but
   nothing enforces them on commit or blocks a regression.

### Major discovery and product gaps

- The **retired multi-tenant SaaS model is only half-removed**. Endpoints are gone,
  but `Organization`/`OrganizationMember` tables, org-scoping middleware, the
  `X-Organization-Id` header contract, and unreachable registration / OAuth /
  phone-OTP / password-reset service functions all remain. One of those dead
  functions (`_render_password_reset_email`) raises `NameError` on every call —
  proof the retired surface is entirely untested.
- **No operator password-change path exists.** The admin password must live in
  plaintext in config or env forever, and is re-hashed from it on every boot.
- **No backup capability** — not a missing dashboard, a missing operational
  capability, for the one artifact the system treats as authoritative.
- **GPL tripwire is armed**: two GPL-origin files are tracked. Private use is fine;
  any distribution requires a clean-room rewrite first.

### Scope limitations and untested areas

Documented in full under *Residual Risks*. In summary: no live exchange or testnet
run was performed (requires operator keys); no browser, accessibility, or load
testing was performed (no browser-driven harness and no built `dashboard/dist` in
this container); no production environment, monitoring stack, or backup artifact
was available to inspect; TimescaleDB and Postgres paths were not exercised.

### Conditions required for release

The original blockers (C1, C2, H1–H5, M8) have been **fixed on this branch**; the
Criticals are verified against a live server. The remaining conditions are:

1. **An independent verification pass** — by someone other than the fix author —
   re-running the C1/C2 checks and exercising the H1 remote-block, the H3 throttle,
   and the CI workflow on a real runner (moving those findings from *Fixed —
   Awaiting Verification* to *Verified*).
2. **PD1** answered — the network-exposure model that finalises H1's disposition
   (localhost/authenticated-proxy only, or public with the loopback guard as one
   layer). Documented, not just decided.
3. **Operational wiring** — schedule `scripts/backup_journal.py` at the target RPO
   (PD5), and handle the H3 `email_login_codes.attempts` schema change on any
   existing deployment (no migration framework yet — Group 4).
4. **PD3** — the GPL/M7 clean-room rewrite before any distribution (not needed while
   private).

### Final recommendation

## **STOP — CONDITIONAL GO**

The control plane's unauthenticated path to the signing keys — the reason for the
earlier NO-GO — is closed and verified live, and every other release blocker is
fixed with tests. What remains is not defect remediation but **verification and
product decisions**: an independent pass to confirm the fixes, PD1's network-exposure
call, and the operational wiring above. Conditional on those, this is releasable
within the reviewed scope. It is a CONDITIONAL GO rather than a GO because the fixes
were authored and self-verified in this same engagement — they must be confirmed by
an independent reviewer before real money is at stake, and the live-exchange path
remains untested by design (operator keys required).

---

## Product Context and Audit Coverage

### Discovered product purpose

AIMOS ("AI Market Operating System") is an autonomous crypto market-intelligence
and trading system for a **single operator running it for themselves**. Despite the
`saas/` package name and the SaaS-titled spec, this is explicitly *not* a
multi-tenant product: `specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md` §1.1
states "the earlier multi-user / multi-tenant SaaS design has been retired," and
§3 describes exactly one admin account seeded from config.

This materially changes the audit's shape: there is **no cross-tenant isolation
surface to attack**, because there is only one tenant. Findings that would be
Critical in a multi-tenant product (IDOR, tenant leakage) are not applicable here.
Conversely, the single-operator model raises the stakes on availability and key
custody — one compromised key is total compromise.

**Sources used:** `README.md`, `CLAUDE.md`, `specs/ARCHITECTURE.md` (1,965 lines,
the build contract), `specs/STATUS.md`, `specs/OPERATIONS.md`, `specs/DEPLOYMENT.md`,
`specs/TESTNET.md`, `specs/ASSISTANT.md`, `specs/MODELS.md`, the SaaS tracker,
`CHANGELOG.md`, all 160 Python modules, the React dashboard, `config/*.yaml`,
`Dockerfile`, `docker-compose.yml`, `run.sh`, `scripts/`, and the 70-file test suite.

### Roles

| Role | Source of truth | Notes |
|---|---|---|
| **Operator / admin** | `saas.admin.*` — one seeded account | The only human role. Full control. |
| **Anonymous** | — | Should have no access. Today has full access in default config (H1). |
| *Organization member / owner* | `OrganizationMember.role` | **Vestigial.** Tables and `require_role()` remain; no endpoint issues a second membership. Not a live role. |

### Critical workflows

1. Paper trading loop — observe → decide → execute → journal (auto-starts with the server).
2. Operator monitoring via 21 live-polling dashboard screens.
3. Runtime control — pause / resume / killswitch, feature toggles.
4. Go-live ladder progression — 6 gates, operator sign-off, boot guard.
5. Live trading — fail-closed behind mandate + ladder + boot guard.
6. Admin login — password → email OTP → JWT.
7. Settings management — runtime config + encrypted exchange keys.
8. Telegram alerts/commands; read-only AI analyst.

### Architecture and trust boundaries

```
observation → intelligence → execution     (pydantic contracts; import-linter enforced, 6/6 kept)
                    ↓
              runtime/serve.py  ──  one uvicorn process:
                                    FastAPI API + React SPA + paper loop + Telegram + monitor
                    ↓
              journal (SQLite, SHA-256 hash chain)  ← system of record
              auth.sqlite (users, tokens, user_settings)
              state/.jwt_secret, state/.settings_key, state/maildrop/  ← key material
```

**The critical trust-boundary observation:** the API, the SPA static files, the
key material, and the trading loop all live inside one process with one working
directory. A file-read primitive anywhere in the HTTP surface reaches the keys —
which is exactly what C1 is.

### Commands executed

Execution environment: Linux 6.18.5, Python 3.11.15, clean virtualenv at
`/tmp/venv-aimos` (`pip install -e '.[dev,data,serve,saas]'`, exit 0).

| Command | Result |
|---|---|
| `pip install -e '.[dev,data,serve,saas]'` (clean venv) | **exit 0** — all pins resolve |
| `pip install -e '.[dev,serve,data,saas]'` (Debian system python) | **exit 1** — `ta==0.11.0` sdist fails against Debian-patched setuptools 68.1.2 (L2) |
| `python -m pytest` | **466 passed, 1 xfailed**, 194.73s |
| `python scripts/check_magic_numbers.py` | **exit 0** — decision-path layers clean |
| `python scripts/check_no_naive_datetime.py` | **exit 0** |
| `lint-imports` | **6 contracts kept, 0 broken** (167 files, 338 deps) |
| `python scripts/check_gpl_tripwire.py` | exit 0 but **⚠️ 2 GPL-origin files tracked** (M7) |
| Custom repro — SPA traversal | **C1 confirmed**, files leaked |
| Custom repro — SaaS-mode UI load | **C2 confirmed**, 401 on `/`, `/login`, `/assets/*` |
| Custom repro — auth brute force | **H3 confirmed**, 3.6 attempts/s/thread, no lockout |
| `npm run build` / browser tests | **NOT RUN** — no Node toolchain; `dashboard/dist` absent |

### Assumptions, contradictions, exclusions

**Assumptions:** the deployment target is the documented `docker-compose.yml`
(bound to `127.0.0.1:8000`) or `run.sh` on an operator machine; there is exactly one
operator; live trading has not yet been enabled.

**Contradictions found:**

| # | Contradiction |
|---|---|
| 1 | `README.md` documents `features.saas_enabled: true` as the way to get login; enabling it makes the UI unreachable (C2). |
| 2 | The SaaS tracker §8 marks "Removed … OAuth, phone OTP, forgot-password" `[x]`; the *endpoints* are removed but the service functions remain (M1). |
| 3 | `CLAUDE.md` hard rule "Secrets are never logged, journaled, or returned to the UI"; login OTPs are logged and written to disk (H2). |
| 4 | The `security_signoff` go-live gate requires a "backup/restore drill"; no backup mechanism exists (H4). |
| 5 | `specs/STATUS.md` says 465 tests; actual is 466 + 1 xfail (L1). |
| 6 | `docker-compose.yml` says "never public"; `Dockerfile` sets `AIMOS_HOST=0.0.0.0` + `EXPOSE 8000`, so a direct `docker run -p` is public (context for H1/C1). |

**Exclusions:** live exchange/testnet execution, browser/accessibility/load testing,
production infrastructure, TimescaleDB and Postgres runtime paths, `vendor/`
third-party internals (reviewed for licensing only), ML training paths (dormant).

---

## Product Completeness Assessment

### Role-to-Capability Matrix

| Capability | Operator/Admin | Anonymous |
|---|---|---|
| Post-login landing page | **Partial** — exists but unreachable when auth is on (C2) | N/A |
| Login / 2FA | **Partial** — flow correct; unthrottled (H3), code leaked (H2) | N/A |
| Logout / session revoke | Implemented | N/A |
| Password change / rotation | **Missing** (M2) | N/A |
| Account recovery | **Missing** — by design (single admin); reset code is dead + broken (M1) | N/A |
| Monitoring dashboards (21 screens) | Implemented | **Implemented — should be Missing** (H1) |
| Runtime controls (pause/kill/features) | Implemented | **Implemented — should be Missing** (H1) |
| Go-live gate sign-off | Implemented | **Implemented — should be Missing** (H1) |
| Exchange key management | Implemented (encrypted at rest) | Not accessible |
| Config overrides via UI | Implemented | Not accessible |
| Reports / exports | **Partial** — AI analyst reports; no CSV/data export |
| Audit log of operator actions | **Partial** — controls journaled `source="ui"`; no auth events (M4) |
| Security / notification preferences | **Missing** — no UI |
| Backup / restore | **Missing** (H4) |

### Entity-to-Operation Matrix

| Entity | Create | View | List | Search | Update | Delete | History | Export | Audit |
|---|---|---|---|---|---|---|---|---|---|
| Decision | Auto | ✅ | ✅ | **Missing** | N/A | N/A | ✅ | **Missing** | ✅ hash chain |
| Trade | Auto | ✅ | ✅ | **Missing** | N/A | N/A | ✅ | **Missing** | ✅ |
| Position | Auto | ✅ | ✅ | N/A | via controls | N/A | ✅ | **Missing** | ✅ |
| Exchange credential | ✅ | metadata only ✅ | ✅ | N/A | ✅ (overwrite) | ✅ | **Missing** | N/A (correct) | **Missing** |
| Go-live gate | N/A | ✅ | ✅ | N/A | ✅ mark/unmark | N/A | `marked_at` only | **Missing** | **Partial** |
| Settings override | ✅ | ✅ | ✅ | N/A | ✅ | **Missing** — no reset-to-default | **Missing** | **Missing** | **Missing** |
| Admin user | config-seeded | ✅ | N/A | N/A | **Missing** (M2) | **Missing** | N/A | N/A | **Missing** |
| Refresh token | Auto | **Missing** — no session list | **Missing** | N/A | rotate ✅ | revoke ✅ | **Missing** | N/A | **Missing** |
| Journal backup | **Missing** | **Missing** | **Missing** | N/A | N/A | N/A | N/A | **Missing** | N/A |

Search/filter/export gaps are **acceptable for a single-operator tool** and are not
release blockers — the dashboard is a live monitor, not a records system, and the
journal is directly queryable. They are logged as an Improvement Opportunity, not a
requirement. The **backup row is the exception** and is escalated as H4.

### Workflow Completeness Matrix

| Workflow | Discover | Authz | Validate | Happy path | Status | Failure | Cancel | Retry | Notify | History | Admin |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Paper trading loop | ✅ | N/A | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Admin login | ✅ | ✅ | ✅ | ✅ | ✅ | **Partial** — no lockout (H3) | ✅ | unbounded (H3) | **Missing** — no alert on failed logins | **Missing** (M4) | **Missing** (M2) |
| Runtime control | ✅ | **Missing** (H1) | ✅ CONFIRM | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Go-live ladder | ✅ | **Missing** (H1) | **Partial** — no ordering (L3) | ✅ | ✅ | ✅ | ✅ unmark | ✅ | ✅ | **Partial** | ✅ |
| Live trading | ✅ | ✅ 3 locks | ✅ | 🟡 dormant | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Exchange key mgmt | ✅ | ✅ | **Partial** — no key validity check on save | ✅ | ✅ | ✅ | ✅ | ✅ | **Missing** | **Missing** | ✅ |
| Backup / restore | **Missing** | — | — | **Missing** | — | — | — | — | — | — | drill only (H4) |
| Deployment | ✅ | — | — | ✅ | **Missing** — no health/readiness endpoint | **Partial** | — | ✅ restart policy | ✅ watchdog | — | **Partial** |

### Dashboard and Reporting Matrix

All 21 screens listed in `specs/STATUS.md` are implemented and live-polling
(verified by source inspection of `dashboard/src/screens/`; **not** verified in a
browser — see Residual Risks). Coverage against operator needs is good: markets,
prices, decision anatomy, mind-map, engines, strategies, models, universe,
positions/risk, trades, balances, connections, controls, go-live, monitor, AI
analyst, decisions, performance, config, agents, settings.

**No additional dashboard is recommended.** Per the audit's own rule, a dashboard is
only warranted when a recurring operator responsibility cannot otherwise be
completed or tracked. Every such responsibility here already has a screen. The
genuine gaps are operational capabilities (backups, auth audit trail, session list,
password change), not new views.

### Missing Requirements and Discovery Gaps

| ID | Capability | Classification | Release-blocking |
|---|---|---|---|
| G1 | Journal backup automation | **Confirmed Missing Requirement** — `security_signoff` gate and `restore_drill.sh` both presuppose it | **Yes** (H4) |
| G2 | Operator password change / rotation | **Strongly Implied Requirement** | No — pre-release |
| G3 | Auth event audit log (login success/failure, key changes) | **Domain-Expected Capability** for a financial system | No — pre-release |
| G4 | Health / readiness endpoints | **Domain-Expected Capability** — `restart: unless-stopped` + watchdog without a readiness probe | No — pre-release |
| G5 | Active session listing / global revoke | **Domain-Expected Capability** | No — post-release |
| G6 | Data export (decisions/trades → CSV) | **Improvement Opportunity** | No |
| G7 | Alert on repeated failed logins | **Strongly Implied** — Telegram alerting already exists | No — post-release |

### Product Decisions Required

| # | Question | Why it matters |
|---|---|---|
| PD1 | Is AIMOS ever exposed beyond localhost/VPN, or is "operator's machine only" a hard constraint? | Decides whether H1 is a blocker or an accepted risk with a documented network control. It does **not** affect C1, which is exploitable from the operator's own browser. |
| PD2 | Should the vestigial multi-tenant schema be deleted or retained? | Retaining it keeps dead auth code and an org-header contract alive (M1). |
| PD3 | Is AIMOS ever distributed to third parties? | If yes, the two GPL-origin files must be clean-room rewritten first (M7). |
| PD4 | Is SMTP mandatory in production, or is `state/maildrop` an accepted fallback? | Affects the H2 fix shape — maildrop may need to be removed entirely rather than gated. |
| PD5 | Target RPO/RTO for the journal? | Sizes the G1 backup design. |

---

## Detailed Findings

---

### C1 — Unauthenticated path traversal in the SPA catch-all route leaks signing keys and secrets

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | **Critical** |
| **Category** | Security — broken access control / arbitrary file read |
| **Disposition** | **Verified** (fixed this branch — see *Remediation Applied*) |
| **Release impact** | Was blocking; fix verified live |
| **Affected roles** | Anonymous (unauthenticated), Operator |
| **Likelihood** | High — trivially exploitable with a single HTTP GET |

**Location:** `aimos/runtime/serve.py:892-895`

```python
@app.get("/{full_path:path}")
def _spa(full_path: str):  # noqa: ANN202 — SPA fallback (client-side routes)
    f = DIST / full_path
    return FileResponse(str(f if f.is_file() else DIST / "index.html"))
```

**Root cause.** `full_path` is joined to `DIST` with no normalization and no
containment check. Starlette percent-decodes path parameters *after* routing, so
`%2e%2e%2f` arrives as `../` and escapes `dashboard/dist`. `pathlib`'s `/` operator
does not resolve or constrain `..`, and an absolute-looking component would replace
the base entirely. `f.is_file()` then happily confirms the escaped target and
`FileResponse` serves it.

Note the asymmetry that makes this easy to miss in manual testing: a *literal*
`../` is normalized away by HTTP clients and by Starlette's path handling, so
`/../secret` correctly returns `index.html`. Only the **percent-encoded** form
reaches the vulnerable join. Testing with a browser or `curl /../x` shows no
problem — which is likely why it survived review.

**Evidence — reproduction.** The repro reconstructs the real directory layout
(`<root>/dashboard/dist`, `<root>/state/`, `<root>/secrets.yaml`, `<root>/.env`) and
mounts the route verbatim from `serve.py`:

```
  state/.jwt_secret     (2 up) -> 200 ESCAPED=True  'JWT-SECRET-VALUE-abc123'
  state/.settings_key   (2 up) -> 200 ESCAPED=True  'FERNET-KEY-VALUE-xyz789'
  secrets.yaml          (2 up) -> 200 ESCAPED=True  'binance:\n  apiKey: REAL-API-KEY\n  secret: REAL-SECRET\n'
  .env                  (2 up) -> 200 ESCAPED=True  'ANTHROPIC_API_KEY=sk-ant-REAL\n'
  /etc/passwd  (deep)         -> 200 ESCAPED=True  'root:x:0:0:root:/root:/bin/bash\ndaemon:...'
  /etc/hostname (deep)        -> 200 ESCAPED=True  'vm\n'
```

In the Docker image the same paths apply verbatim: `WORKDIR /app`, dist at
`/app/dashboard/dist`, and `./state` bind-mounted at `/app/state`.

**Evidence — confirmed against the live running application (Pass 2).** The
dashboard was built (`npm run build`) and the real server started
(`python -m aimos.runtime.serve`, paper mode, port 8011). `curl` against the running
process:

```
200  /%2e%2e%2f%2e%2e%2fstate/.jwt_secret     -> cDUZGGWZzhd3p8LuSpTZMxfJwidHgX3B-hzr3ZpivH4=
200  /%2e%2e%2f%2e%2e%2fstate/aimos.sqlite     -> SQLite format 3 ...   (the journal — system of record)
200  /%2e%2e%2f%2e%2e%2fCLAUDE.md              -> # CLAUDE.md — working rules ...
200  /%2e%2e%2f%2e%2e%2fconfig/mandate.yaml    -> # Live-trading mandate — fail-closed contract ...
```

Refinement of the reach claim: from `dashboard/dist` (two levels below repo root),
a deep `../../../../etc/passwd` does **not** reach filesystem root — it returns the
SPA `index.html`. The exploitable reach is **everything within the repo/container
tree at that depth**, which already includes the JWT signing key, the settings
encryption key, the plaintext `state/maildrop/*` OTP codes, the SQLite journal, and
all config. That is complete compromise; reaching `/etc/passwd` is not required.

**Evidence — full kill chain proven (Pass 2).** Using the secret leaked above, a
forged admin access token was minted and fed to the application's own decoder:

```
leaked secret: cDUZGGWZzhd3...(44 chars)
forged admin access token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ ...
decode_token ACCEPTS forged token -> payload: {'sub': 'admin', 'org': 'attacker', 'type': 'access'}
```

`aimos.saas.security.decode_token(..., token_type="access")` accepts the forged
token. This closes the loop: traversal → leak signing key → mint admin session. The
authentication layer is not merely bypassable, it is forgeable from an
unauthenticated GET.

**Impact.**

- *Security:* `state/.jwt_secret` is the HS256 signing key. With it an attacker
  mints a valid admin access token (`{"sub": "admin", "org": ..., "type": "access"}`)
  and authenticates as the operator — so C1 defeats the entire auth layer, not just
  one endpoint. `state/.settings_key` is the Fernet key that decrypts stored
  **exchange API credentials**. `state/maildrop/` holds plaintext 2FA codes (H2).
- *Business:* combined, these give an attacker the operator's exchange keys. If
  those keys are ever funded and withdrawal-enabled, this is direct financial loss.
  Even withdrawal-disabled keys permit adversarial trading.
- *Operational:* also reads `/etc/passwd`, `/etc/hostname`, and any file the process
  user can read — useful for onward escalation.

**Recommended solution.** Constrain the resolved path to `DIST` and reject anything
outside it. `Path.resolve()` normalizes `..` and symlinks; compare with
`is_relative_to` (3.9+), then serve `index.html` for any miss rather than 404ing, to
preserve SPA client-side routing.

```python
# aimos/runtime/serve.py
@app.get("/{full_path:path}")
def _spa(full_path: str):  # noqa: ANN202 — SPA fallback (client-side routes)
    index = DIST / "index.html"
    root = DIST.resolve()
    try:
        candidate = (root / full_path).resolve()
    except (OSError, ValueError):
        return FileResponse(str(index))
    # Serve a real file only when it is genuinely inside the dist tree.
    if candidate.is_file() and candidate.is_relative_to(root):
        return FileResponse(str(candidate))
    return FileResponse(str(index))
```

Recommended defense in depth (each independently valuable):

1. Move key material out of the working-directory subtree — e.g. honour an
   `AIMOS_STATE_DIR` outside `/app`, or store the JWT secret only in
   `AIMOS__SAAS__JWT_SECRET`.
2. Prefer Starlette's `StaticFiles(directory=DIST, html=True)` for the whole SPA;
   it performs its own containment check, replacing hand-rolled joining.
3. Ensure the traversal fix is applied **before** the SaaS middleware exemption
   changes in C2 — otherwise the C2 fix widens C1's reach to unauthenticated users
   in SaaS mode too.

**Database / migration / deployment considerations.** None schema-side. After
deploying the fix, **rotate both keys**, because they must be assumed disclosed:
delete `state/.jwt_secret` (regenerates on boot; invalidates all sessions) and
rotate every exchange API key that was stored while the vulnerable build ran.
Rotating `state/.settings_key` requires re-entering exchange credentials, since
existing ciphertext becomes undecryptable.

**Regression risks.** The `resolve()` call follows symlinks — if any deployment
symlinks assets into `dist`, targets outside the tree would now be refused
(correctly, but it is a behavior change). Verify the dashboard's hashed asset
filenames still load. `is_relative_to` requires Python ≥3.9; the project requires
≥3.11, so this is safe.

**Tests to add.**

- `tests/test_serve.py::test_spa_rejects_encoded_traversal` — assert
  `/%2e%2e%2fsecret` returns `index.html`, never the file body.
- Parametrized over encoded, double-encoded, absolute, and backslash variants.
- `test_spa_serves_real_assets` — a genuine file inside `dist` is still served.
- A regression test asserting no response body ever contains the `.jwt_secret`
  contents.

**Verification steps.**

1. Apply the fix; `python -m pytest tests/test_serve.py -v`.
2. Start the server; run the three `curl` commands above — each must return the
   `index.html` body, not file contents.
3. Re-run the traversal repro; every row must report `ESCAPED=False`.
4. Confirm the dashboard still loads and client-side routes still resolve.

**Similar locations inspected.** `app.mount("/assets", StaticFiles(...))`
(`serve.py:886`) is **safe** — Starlette's `StaticFiles` enforces containment. The
`_index` route (`serve.py:888-890`) is safe (fixed path). No other `FileResponse`,
`send_file`, or user-controlled path join exists in the codebase — searched across
all 160 Python modules. `_dev_drop` (`aimos/saas/email.py:100-104`) builds a
filename from an email address but is not driven by an HTTP path parameter; it is
covered separately under H2.

---

### C2 — Enabling SaaS authentication makes the dashboard, its login page, and all static assets unreachable

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | **Critical** |
| **Category** | Business logic / availability / architecture |
| **Disposition** | **Verified** (fixed this branch — see *Remediation Applied*) |
| **Release impact** | Was blocking; fix verified live + in-browser |
| **Affected roles** | Operator |
| **Likelihood** | Certain — deterministic, occurs on every request |

**Location:** `aimos/api/server.py:102-125` (middleware) interacting with
`aimos/runtime/serve.py:877-895` (SPA mount)

```python
if get_saas_config().enabled:
    path = request.url.path
    public = path == "/api/v2/status" or path.startswith("/auth/") or path.startswith("/api/v2/")
    if not public:
        token = _extract_bearer(request)
        if not token:
            return JSONResponse({"detail": "Authorization required"}, status_code=401)
```

**Root cause.** The exemption list enumerates only API paths. It was written as if
the app served JSON exclusively, but the same FastAPI app also serves the React SPA
at `/`, `/{full_path:path}`, and `/assets/*` (mounted afterwards in
`_mount_dashboard`). Those paths are not in the exemption list, so the middleware
demands a bearer token for the very HTML and JavaScript the operator needs in order
to obtain a token. The dependency is circular: you cannot log in without the login
page, and you cannot load the login page without having logged in.

**Evidence — reproduction.** Using the real `create_app` middleware with
`AIMOS__SAAS__ENABLED=true` and the real `_mount_dashboard` routes:

```
  saas enabled = True
  GET /                      -> 401  '{"detail":"Authorization required"}'
  GET /login                 -> 401  '{"detail":"Authorization required"}'
  GET /assets/app.js         -> 401  '{"detail":"Authorization required"}'
  GET /api/v2/status         -> 200  '{"saas_enabled":true}'
  GET /api/decisions         -> 401  '{"detail":"Authorization required"}'
  GET /metrics               -> 401  '{"detail":"Authorization required"}'
```

Reproduction against a running instance:

```bash
AIMOS__SAAS__ENABLED=true \
AIMOS__SAAS__ADMIN__EMAIL=admin@example.com \
AIMOS__SAAS__ADMIN__PASSWORD='A-strong-password-123!' \
python -m aimos.runtime.serve &
curl -si http://localhost:8000/ | head -1     # HTTP/1.1 401 Unauthorized
```

**Impact.**

- *User:* the documented way to secure AIMOS (`README.md`: "Single-admin login /
  settings UI — set `features.saas_enabled: true`") produces a completely unusable
  dashboard. There is no workaround short of disabling authentication.
- *Security:* this is why C2 is Critical rather than merely a High availability bug.
  An operator who tries to enable auth, finds the UI broken, and reverts to
  `saas_enabled: false` lands in H1 — a fully unauthenticated trading control API.
  The defect actively pushes deployments into the insecure configuration.
- *Business:* the entire single-admin auth feature — the most recent two commits of
  work — cannot be used in production as shipped.

**Why the tests did not catch it.** `tests/test_saas.py` exercises the auth
endpoints directly via `TestClient` against `create_app`, but `_mount_dashboard` is
only called from `build_app()` in `serve.py`, and no test builds the full app with
SaaS enabled *and* a populated `dashboard/dist`. The two halves are each tested; the
interaction between them is not.

**Recommended solution.** Exempt non-API paths from the token requirement and let
the API surface remain protected. The SPA is public static content; it holds no
secrets and the API it calls is authenticated independently.

```python
# aimos/api/server.py
_PUBLIC_PREFIXES = ("/auth/", "/api/v2/", "/assets/")

def _is_public(path: str) -> bool:
    # Static SPA shell + auth endpoints are public; the SPA authenticates itself
    # against /auth/* and then calls the protected /api/* surface with a token.
    if path in ("/", "/favicon.ico", "/api/v2/status"):
        return True
    if path.startswith(_PUBLIC_PREFIXES):
        return True
    # Anything that is not an API route is SPA shell / client-side routing.
    return not path.startswith("/api/") and path != "/metrics"

@app.middleware("http")
async def saas_tenant_scope(request: Request, call_next):
    if get_saas_config().enabled and not _is_public(request.url.path):
        ...  # unchanged token + org checks
    return await call_next(request)
```

This must be paired with the C1 fix — once non-API paths are public in SaaS mode,
the traversal would otherwise be reachable without a token there too.

For `/metrics`, decide explicitly (see M6): either keep it authenticated and
configure the scraper with a token, or expose it on a separate bound port.

**Regression risks.** Broadening the public set risks unintentionally exposing a
future non-`/api/` endpoint. Mitigate by making the rule allow-list-shaped for
static assets specifically, and by adding the test below so any new unprotected
route is caught. Confirm `/api/*` endpoints still 401 without a token after the
change — that assertion is the guard rail.

**Tests to add.**

- `tests/test_saas.py::test_spa_is_reachable_when_saas_enabled` — build the full app
  via `build_app()` with a temporary `dashboard/dist` containing `index.html`,
  SaaS enabled, and assert `GET /` returns 200 and the HTML body.
- `test_assets_reachable_when_saas_enabled` — `GET /assets/<file>` returns 200.
- `test_api_still_requires_token_when_saas_enabled` — `GET /api/decisions` returns
  401 (guards against over-broad exemption).
- `test_login_flow_end_to_end_through_spa` — load `/`, POST `/auth/login`, POST
  `/auth/login/verify`, then call `/api/decisions` with the token: 200.

**Verification steps.**

1. Build the dashboard (`cd dashboard && npm install && npm run build`).
2. Start with `AIMOS__SAAS__ENABLED=true` and admin credentials set.
3. `curl -si http://localhost:8000/ | head -1` → `HTTP/1.1 200 OK`.
4. In a browser: load the dashboard, complete password + OTP login, confirm screens
   populate.
5. `curl -si http://localhost:8000/api/decisions | head -1` → `HTTP/1.1 401`.

**Similar locations inspected.** The `/api/v2/` blanket exemption is acceptable
because every route under it declares `Depends(get_current_user)`
(`aimos/saas/router.py:134-201`) — verified route by route. `/api/v2/status` is
intentionally public and returns only `{"saas_enabled": bool}`, which is not
sensitive.

---

### H1 — Trading control API is fully unauthenticated in the default configuration

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | **High** |
| **Category** | Security — missing authentication / broken access control |
| **Disposition** | **Fixed — Awaiting Verification** (loopback-default host + loopback-only control endpoints — see *Remediation Applied*; final disposition depends on PD1) |
| **Release impact** | Accidental exposure + anonymous remote control closed; PD1 finalises |
| **Affected roles** | Anonymous |
| **Likelihood** | Medium — requires network reach to the port |

**Location:** `aimos/api/server.py:109` (`if get_saas_config().enabled:`), guarding
`aimos/api/server.py:178-197` and `295-315`. Default is `enabled: false`
(`aimos/saas/settings.py:115`).

**Root cause.** All authentication is conditional on `saas_enabled`, which defaults
to `false`. In that mode the middleware is a no-op and every endpoint — including
state-changing controls — is open. `_require_confirm` (`server.py:347-349`) checks
only for the literal string `"CONFIRM"` in the request body; it is a UI
double-confirmation affordance, **not** an authorization control, and provides no
security against a caller who has read the source.

Unauthenticated in default config:

| Endpoint | Effect |
|---|---|
| `POST /api/control/killswitch` | Halts the trading loop |
| `POST /api/control/pause` / `resume` | Pauses/resumes trading globally or per symbol |
| `POST /api/control/feature` | Toggles `scalp` / `cross_exchange` strategies |
| `POST /api/control/golive` | **Marks go-live ladder gates passed** |
| `POST /api/assistant` | Invokes the LLM — billable, attacker-controlled prompt |
| `GET /api/*` | Full read of positions, balances, trades, config, connections |

**Impact.**

- *Availability:* an attacker halts trading, or resumes it when the operator
  deliberately paused.
- *Safety-model erosion:* `POST /api/control/golive` writes to `state/go_live.json`,
  the sole record backing `guard_live_boot`. An attacker can mark all six gates
  passed. This does not by itself start live trading — `mode=live` or
  `mandate.enabled` is still required, and `FeatureController.LOCKED`
  (`aimos/runtime/features.py:17-23`) correctly refuses to flip those from the API
  (**verified**). But it silently pre-satisfies one of the three independent locks,
  so the *next* legitimate live boot proceeds without the operator's real sign-off.
  The README's "three independent locks" claim is weakened to two.
- *Financial:* `POST /api/assistant` calls the Anthropic API on every request with
  no throttle — an unauthenticated cost-amplification vector.
- *Privacy:* full disclosure of trading positions, balances, and strategy config.

**Mitigating factors (documented honestly).** `docker-compose.yml:19` binds
`127.0.0.1:8000` and comments "never public — behind VPN/SSH tunnel (§23.4)". This is
a real and sensible control. It is **not sufficient** as the only control: the
`Dockerfile` sets `AIMOS_HOST=0.0.0.0` and `EXPOSE 8000`, so `docker run -p 8000:8000`
is public; `serve.py:930` defaults `AIMOS_HOST` to `0.0.0.0`; and localhost binding
does not defend against another local user, a compromised local process, or
DNS-rebinding from the operator's own browser.

Cross-origin JSON `POST` from a malicious page is blocked in practice: there is no
`CORSMiddleware` anywhere (verified by search), so preflight fails. This limits
drive-by CSRF but not direct or rebinding attacks.

**Recommended solution.** Authentication should not be optional for state-changing
endpoints. Preferred: make auth mandatory and remove the `saas_enabled` escape
hatch for controls.

```python
# aimos/api/server.py — illustrative
_MUTATING_PREFIX = "/api/control/"

@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if get_saas_config().enabled:
        ...  # existing checks (with the C2 public-path fix)
    elif path.startswith(_MUTATING_PREFIX) or path == "/api/assistant":
        # Local-only mode: refuse control actions from non-loopback callers so a
        # misconfigured bind cannot expose the kill switch or the go-live ladder.
        client = request.client.host if request.client else ""
        if client not in ("127.0.0.1", "::1"):
            return JSONResponse({"detail": "control requires authentication"}, status_code=401)
    return await call_next(request)
```

Additionally: default `AIMOS_HOST` to `127.0.0.1` rather than `0.0.0.0`
(`serve.py:930` and `Dockerfile`), requiring an explicit opt-in to bind publicly.
That single change closes the most likely accidental exposure.

If PD1 confirms AIMOS is only ever reachable behind an authenticated reverse proxy,
H1 may be downgraded to **Accepted Risk** — but that decision must be written into
`specs/OPERATIONS.md` with the proxy configuration, and it does not mitigate C1.

**Regression risks.** A loopback check breaks legitimate access from another host
(e.g. an operator on a LAN) — hence the explicit opt-in env var. Docker bridge
networking makes container-internal callers non-loopback; verify the watchdog and
Telegram services, which call the API, still function (they currently use the same
host network path — confirm before shipping).

**Tests to add.** `test_control_endpoints_reject_remote_client_without_saas`;
`test_control_endpoints_allow_loopback`; `test_golive_endpoint_requires_auth_when_saas_enabled`.

**Verification steps.** With `saas_enabled: false`, from a second host on the
network: `curl -X POST http://<host>:8000/api/control/killswitch -d '{"confirm":"CONFIRM"}'
-H 'Content-Type: application/json'` must return 401 and the loop must remain running
(check `/api/journal/stats` still advances).

**Similar locations inspected.** Every `@app.post` in `aimos/api/server.py` was
enumerated; all six mutating routes share this exposure. `aimos/telegram/` has its
own nonce-based confirmation flow, reviewed separately and not affected.

---

### H2 — Login 2FA codes are written to disk in plaintext and logged at WARNING by default

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | **High** |
| **Category** | Security / privacy — secret handling |
| **Disposition** | **Fixed — Awaiting Verification** (no body in logs; maildrop opt-in + `0600` — see *Remediation Applied*) |
| **Release impact** | Was blocking; fixed |
| **Affected roles** | Operator |
| **Likelihood** | High — default behavior, no misconfiguration required |

**Location:** `aimos/saas/email.py:51-56` (logging), `aimos/saas/email.py:97` and
`100-104` (`_dev_drop`)

```python
if not smtp.host or not smtp.username:
    log.warning("email_not_sent_no_smtp", to=to, subject=subject, body=text_body[:200])
    return
...
def send_login_code_email(to: str, code: str) -> None:
    ...
    send_email(to, "AIMOS login code", text, html)
    _dev_drop(f"login-{to}", code)          # <- runs unconditionally

def _dev_drop(prefix: str, code: str) -> None:
    drop_dir = Path("state") / "maildrop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    (drop_dir / f"{prefix}.txt").write_text(code, encoding="utf-8")
```

**Root cause.** Two separate defects with the same consequence. (1) The no-SMTP
fallback logs the rendered body, which contains the code — and SMTP is unconfigured
by default (`smtp.host: ""`, `aimos/saas/settings.py:26`), so this is the out-of-box
path. (2) `_dev_drop` is called **after** `send_email` returns, outside any
conditional, so the code is written to `state/maildrop/login-<email>.txt` in
plaintext **even when SMTP is correctly configured**. The docstring says "for local
development", but nothing restricts it to development. Neither file is
mode-restricted (contrast `state/.jwt_secret`, which is `chmod 0600`, and
`state/.settings_key`, also `0600`).

This directly violates a stated hard rule in `CLAUDE.md`: *"Secrets are never
logged, journaled, or returned to the UI."*

**Evidence.** Captured during the H3 brute-force measurement — the OTP appears in
the application's own log stream at WARNING level:

```
2026-07-30 13:53:05 [warning  ] email_not_sent_no_smtp   body=Your AIMOS login code is: 881267

It expires in 10 minutes. subject=AIMOS login code to=admin@example.com
```

And on disk after any login attempt:

```bash
$ cat state/maildrop/login-admin@example.com.txt
881267
```

**Impact.**

- *Security:* the second authentication factor is written in cleartext to two
  locations that outlive the 10-minute code window (the file is overwritten only on
  the next login; the log line is permanent).
- **Chained with C1 this is a complete 2FA bypass**: an attacker who knows the admin
  password fetches
  `/%2e%2e%2f%2e%2e%2fstate/maildrop/login-admin%40example.com.txt`, reads the live
  code, and completes login. C1 already yields the JWT signing key, so this is a
  second independent path to the same outcome — which is why fixing C1 alone is not
  sufficient.
- *Operational:* logs are routinely shipped to aggregators, screen-shared, and
  pasted into bug reports. Any of those now discloses a live authentication factor.

**Recommended solution.** Never render a secret into a log field, and gate the
maildrop behind an explicit development flag.

```python
# aimos/saas/email.py
def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    cfg = get_saas_config()
    smtp = cfg.smtp
    if not smtp.host or not smtp.username:
        # Never log the body — it carries one-time codes (CLAUDE.md hard rule).
        log.warning("email_not_sent_no_smtp", to=to, subject=subject)
        return
    ...

def _dev_drop(prefix: str, code: str) -> None:
    """Write the code to state/maildrop — DEV ONLY, opt-in."""
    if os.environ.get("AIMOS_DEV_MAILDROP", "").lower() not in ("1", "true", "yes"):
        return
    drop_dir = Path("state") / "maildrop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    path = drop_dir / f"{prefix}.txt"
    path.write_text(code, encoding="utf-8")
    os.chmod(path, 0o600)
```

Consider also failing closed at startup when `saas.enabled` is true and SMTP is
unconfigured, rather than silently degrading to a fallback that cannot deliver the
second factor — an operator can otherwise believe 2FA is protecting them when the
code is only being written to a local file.

**Deployment considerations.** Purge existing artifacts as part of the fix:
`rm -rf state/maildrop` and scrub any retained logs containing
`email_not_sent_no_smtp`. Document `AIMOS_DEV_MAILDROP` in `specs/OPERATIONS.md`.

**Regression risks.** Developers relying on the maildrop for local login will need
the new env var — call this out in `specs/DEPLOYMENT.md`. `tests/test_saas.py`
obtains codes via the service-layer return value, not the maildrop, so tests are
unaffected (verified).

**Tests to add.** `test_login_code_not_written_to_disk_by_default`;
`test_login_code_not_in_log_output` (capture structlog output and assert the code
does not appear); `test_maildrop_written_only_when_dev_flag_set`.

**Verification steps.** Start with SaaS enabled and no SMTP; POST `/auth/login`;
confirm (a) `state/maildrop/` does not exist, (b) the log line contains `to` and
`subject` but no digits from the code, (c) with `AIMOS_DEV_MAILDROP=1` the file
appears with mode `0600`.

**Similar locations inspected.** `send_verification_email` and
`send_password_reset_email` call `_dev_drop` identically (`email.py:82, 89`) — both
are dead code (M1) but must be fixed with the same change. `aimos/saas/sms.py` has a
`console` driver default — reviewed: it logs OTPs the same way and is also dead code,
but should be covered by the same fix. No other secret-logging was found: exchange
credentials are never logged (verified by search across all modules), and
`get_exchanges()` correctly strips `apiKey`/`secret` before returning to the UI
(`settings_store.py:110-122`).

---

### H3 — No rate limiting or lockout on authentication; unbounded OTP guessing and unauthenticated CPU exhaustion

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | **High** |
| **Category** | Security — authentication hardening / availability |
| **Disposition** | **Fixed — Awaiting Verification** (OTP burn-after-5 + `/auth/*` throttle — see *Remediation Applied*) |
| **Release impact** | Was blocking; fixed |
| **Affected roles** | Anonymous, Operator |
| **Likelihood** | Medium |

**Location:** `aimos/saas/auth_service.py:551-576` (`send_login_otp`),
`aimos/saas/auth_service.py:579-607` (`verify_login_otp`), exposed at
`aimos/saas/router.py:91-102`.

**Root cause.** There is no inbound HTTP rate limiting anywhere in the application —
confirmed by searching for `slowapi`, `Limiter`, `429`, `attempts`, and `lockout`
across all modules. The only rate limiting present (`aimos/data/ratelimit.py`) is
*outbound* budgeting against exchange APIs and is unrelated. Consequently:

1. `/auth/login` accepts unlimited password attempts with no lockout, no delay, and
   no alerting.
2. `/auth/login/verify` accepts unlimited OTP guesses. The code record is marked
   `used = True` **only on success** (`auth_service.py:596`); a wrong guess leaves it
   live for the remainder of its 10-minute TTL.
3. There is no attempt counter on `EmailLoginCode` at all
   (`aimos/saas/models.py` — fields are `id, user_id, code_hash, expires_at, used`).

**Evidence — measured.**

```
(a) /auth/login: 20/20 wrong-password attempts rejected, no lockout triggered.
    wall time 5.49s -> 3.6 attempts/sec/thread (275 ms of server bcrypt work per unauthenticated request)
    correct password still accepted after 20 failures (no lockout)

(b) /auth/login/verify: 20 wrong OTP guesses rejected; code NOT invalidated.
    3.6 guesses/sec/thread
    real code STILL valid after 20 wrong guesses -> tokens issued OK

    6-digit space = 1e6; at 4 guesses/s/thread a single 10-min code window allows ~2,184 guesses
    => ~0.22% success per window per thread; parallel clients scale this linearly (no server-side attempt cap).
```

**Impact — assessed proportionately.**

- *OTP brute force:* bcrypt's cost is a genuine partial mitigation — a single thread
  gets ~0.22% per 10-minute window, so this is **not** a trivially broken second
  factor. But the attacker controls concurrency and can request a fresh code
  repeatedly, and industry practice is a hard cap of 5–10 attempts. The gap between
  "slow" and "capped" is what makes this High rather than Critical, and it only
  matters once the password is known — which H2 and C1 both make easier.
- *CPU exhaustion (the stronger vector):* each unauthenticated `/auth/login` request
  costs the server **275 ms of bcrypt work**. A few dozen concurrent requests
  saturate every core. This process is not just an API — `runtime/serve.py` runs the
  **paper/live trading loop, Telegram alerting, and the monitor agent in the same
  process**. Starving it of CPU degrades or stalls trading decisions and alert
  delivery. For a trading system, an unauthenticated remote DoS against the decision
  loop is a serious availability finding in its own right.
- *No detection:* no failed-login metric, log event, or alert exists, so a sustained
  attack is invisible to the operator (relates to G3/G7).

**Recommended solution.** Three independent controls; implement all three.

```python
# 1. Cap attempts per code — add to aimos/saas/models.py
class EmailLoginCode(Base):
    ...
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

# 2. Enforce the cap — aimos/saas/auth_service.py
MAX_OTP_ATTEMPTS = 5  # noqa: magic — security policy constant, not a tunable

def verify_login_otp(session: Session, email: str, code: str) -> AuthResult:
    ...
    if record is None:
        raise AuthError("Invalid or expired code")
    if record.attempts >= MAX_OTP_ATTEMPTS:
        record.used = True          # burn the code; operator must request a new one
        session.commit()
        raise AuthError("Too many attempts — request a new code")
    if not verify_password(code, record.code_hash):
        record.attempts += 1
        session.commit()
        raise AuthError("Invalid or expired code")
    ...
```

```python
# 3. Throttle the endpoints themselves — aimos/api/server.py (illustrative;
#    a small in-process fixed-window limiter avoids a new dependency)
_AUTH_WINDOW_SECONDS = 60.0   # noqa: magic — structural
_AUTH_MAX_PER_WINDOW = 10     # noqa: magic — security policy

@app.middleware("http")
async def throttle_auth(request: Request, call_next):
    if request.url.path.startswith("/auth/"):
        key = request.client.host if request.client else "unknown"
        if _limiter.hit(key, _AUTH_MAX_PER_WINDOW, _AUTH_WINDOW_SECONDS):
            return JSONResponse({"detail": "too many requests"}, status_code=429)
    return await call_next(request)
```

Also emit a structured log event and a Telegram alert on repeated failures (G7) —
the alerting channel already exists and this is a small addition.

**Database / migration considerations.** Adding `EmailLoginCode.attempts` requires a
schema change. The project has **no migration tooling** (no Alembic; `db.py:41` uses
`Base.metadata.create_all`, which does not alter existing tables). For a
single-operator deployment the pragmatic path is to drop and recreate the
`email_login_codes` table on upgrade — it holds only transient codes, so no
meaningful data is lost. This gap is itself worth noting: see M-note under
Remediation, *no migration framework exists* for the auth DB.

**Regression risks.** An IP-based limiter behind a reverse proxy sees the proxy's IP
and would throttle the operator globally — honour `X-Forwarded-For` only when a
trusted-proxy list is configured, never blindly. Ensure the limiter's state is
per-process; with a single uvicorn worker (the current deployment) this is correct.

**Tests to add.** `test_otp_locked_after_max_attempts`;
`test_otp_code_burned_after_cap`; `test_login_throttled_returns_429`;
`test_throttle_resets_after_window`.

**Verification steps.** Request a code, submit 5 wrong values (each 401), then submit
the **correct** code — it must be rejected. Request a new code; correct value
succeeds. Separately, issue 15 rapid `/auth/login` calls and confirm the 11th returns
429.

**Similar locations inspected.** No endpoint in the application has any throttle.
`/api/assistant` (LLM-backed, billable) is the other endpoint most in need of one —
covered under H1. `refresh_access_token` (`auth_service.py:444-477`) performs a
bcrypt comparison per candidate token in a loop, giving the same CPU-cost profile;
it should be throttled by the same middleware.

---

### H4 — No backup mechanism exists, and the restore drill reports success when no backup is found

| Field | Value |
|---|---|
| **Classification** | Confirmed Missing Requirement |
| **Severity** | **High** |
| **Category** | Operations / data durability |
| **Disposition** | **Fixed — Awaiting Verification** (`scripts/backup_journal.py` added; drill now fails without a backup — see *Remediation Applied*) |
| **Release impact** | Was blocking; scheduling at the target RPO is the remaining ops step |
| **Affected roles** | Operator |
| **Likelihood** | Certain — the capability is simply absent |

**Location:** `scripts/restore_drill.sh:9-11`; absence across the whole repository.

```bash
if [[ ! -f "$BACKUP" ]]; then
  echo "no backup at $BACKUP — nothing to drill (create one first)"; exit 0
fi
```

**Root cause and evidence.** A repository-wide search for `backups/`,
`journal-latest`, `pg_dump`, `sqlite3 ... backup`, and `.backup(` across `*.py`,
`*.sh`, `*.yml`, `*.yaml`, and `*.md` — excluding the drill script itself — returned
**zero matches**. Nothing in the application, the compose file, the Dockerfile, or
the documentation ever creates a backup. `docker-compose.yml` defines no backup
service and the `pgdata` volume has no snapshot policy.

Meanwhile the restore drill **exits 0** — the success status — when the backup is
missing. A drill wired into any automation would report PASS forever on a system
that has never had a backup.

This matters because `README.md` designates SQLite as "the hash-chained decision/trade
journal (`state/aimos.sqlite`), **the system of record**", and the go-live ladder's
`security_signoff` gate (`aimos/runtime/golive.py:26-27`) explicitly requires
"backup/restore drill" — a gate the operator would sign off against a drill that
cannot fail.

**Impact.**

- *Data:* total, unrecoverable loss of the trading journal on disk failure, volume
  deletion, or container removal. The journal is the audit trail, the input to the
  learning layer, and the evidence base for the `paper_4wk` go-live gate — losing it
  resets the go-live timeline and destroys the compliance record.
- *Operational:* the go-live safety ladder contains a gate that cannot be honestly
  satisfied, which undermines confidence in the other five.
- *Compliance:* a financial system with no recovery capability and a hash-chained
  "audit journal" that can vanish entirely.

**Recommended solution.** Two parts — make the drill honest, then add the capability.

```bash
# scripts/restore_drill.sh — fail when there is nothing to drill
if [[ ! -f "$BACKUP" ]]; then
  echo "FAIL: no backup at $BACKUP — a drill with no backup is not a pass" >&2
  exit 1
fi
```

```python
# scripts/backup_journal.py (new) — illustrative
"""Consistent point-in-time backup of the hash-chained journal (§23.5)."""
import sqlite3, shutil
from datetime import datetime, timezone
from pathlib import Path

def backup(src: str = "state/aimos.sqlite", dest_dir: str = "backups") -> Path:
    dest = Path(dest_dir); dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = dest / f"journal-{stamp}.sqlite"
    # sqlite3's online backup API is consistent under concurrent writes —
    # a plain file copy of a live WAL database is not.
    with sqlite3.connect(src) as s, sqlite3.connect(out) as d:
        s.backup(d)
    latest = dest / "journal-latest.sqlite"
    shutil.copy2(out, latest)
    return out
```

Then schedule it (a compose service on a timer, or the existing APScheduler
runtime), verify each backup by running `python -m aimos.journal.verify` against it
immediately after creation, apply a retention policy, and document RPO/RTO in
`specs/OPERATIONS.md` once PD5 is answered. Note that `AIMOS__SAAS__DATABASE_URL`
may point at Postgres in the compose deployment — the auth/settings DB needs its own
`pg_dump` schedule, and `state/.settings_key` must be backed up separately and
securely or the encrypted exchange credentials are unrecoverable.

**Regression risks.** `sqlite3.Connection.backup` holds a read lock; on a large
journal under a fast tick loop this could briefly contend. Run it off the trading
thread and measure. Do **not** substitute a plain `cp` — with WAL mode that yields a
torn database.

**Tests to add.** `test_backup_creates_verifiable_copy` — back up a populated
journal, run the hash-chain `verify()` on the copy, assert it passes;
`test_restore_drill_fails_without_backup` — assert exit code 1.

**Verification steps.** Run a paper session to populate the journal; run the backup
script; `python -m aimos.journal.verify backups/journal-latest.sqlite` → chain valid;
`./scripts/restore_drill.sh` → PASS; delete the backup and re-run → **exit 1**.

**Similar locations inspected.** The go-live ladder state (`state/go_live.json`), the
auth DB (`state/auth.sqlite`), and both key files (`state/.jwt_secret`,
`state/.settings_key`) have the same zero-backup exposure and should be covered by
the same routine — with the keys handled as secrets, not dropped into `backups/`
alongside the journal.

---

### H5 — No CI/CD pipeline; the four documented quality gates are unenforced

| Field | Value |
|---|---|
| **Classification** | Confirmed Missing Requirement |
| **Severity** | **High** |
| **Category** | Deployment / release engineering |
| **Disposition** | **Fixed — Awaiting Verification** (`.github/workflows/ci.yml` added — see *Remediation Applied*; not yet exercised on the runner) |
| **Release impact** | Was blocking; needs one green run on the CI runner to confirm |
| **Affected roles** | Operator (as maintainer) |
| **Likelihood** | Certain |

**Location:** absence of `.github/` (or any CI configuration) in the repository.

**Root cause and evidence.** `ls -a .github` → no such directory. No GitLab, CircleCI,
Jenkins, or other pipeline configuration exists anywhere. The only automation is
`.pre-commit-config.yaml`, which runs `import-linter`, `no-naive-datetime`,
`magic-number-lint`, and `gpl-tripwire` — **but not the test suite**, and only on
developer machines where `pre-commit install` has been run. Nothing runs on push,
nothing blocks a merge, and nothing verifies a build artifact.

`CLAUDE.md` mandates four gates after every change (`pytest`, magic-number lint,
naive-datetime lint, `lint-imports`). All four pass today — verified in this audit —
but that is the result of discipline, not enforcement.

**Impact.**

- *Regression safety:* the strongest asset this project has is its 466-test suite and
  its mechanically-enforced architecture. None of it is wired to a gate. A single
  push can break the layering contract or the determinism guarantees with no signal.
- *Traceability:* no versioned, reproducible build artifact traceable to a commit.
  The Docker image is built ad hoc on the deployment host.
- *Release engineering:* per the audit's deployment checklist — required build, lint,
  type, test, migration, and security checks; failed gates blocking deployment;
  artifacts traceable to a source commit — **none** are satisfied.

**Recommended solution.**

```yaml
# .github/workflows/ci.yml — illustrative
name: CI
on: [push, pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e '.[dev,data,serve,saas]'
      - run: python -m pytest -q
      - run: python scripts/check_magic_numbers.py
      - run: python scripts/check_no_naive_datetime.py
      - run: lint-imports
      - run: python scripts/check_gpl_tripwire.py
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd dashboard && npm ci && npm run build
```

Add on top: a dependency vulnerability scan (`pip-audit`) and a secret scan
(`gitleaks`) — neither exists today and both are directly relevant to the findings
above. Note that `check_gpl_tripwire.py` currently **exits 0 while printing a
warning** (M7); if it is used as a distribution gate it must exit non-zero.

**Regression risks.** CI will surface the `ta==0.11.0` build behavior (L2) on some
runner images — pin `setuptools` in the workflow or use a runner with a modern
toolchain. Expect the first CI run to be slow (~3.5 min for tests alone).

**Tests to add.** Not applicable — this *is* test infrastructure. Verify by opening a
deliberately-failing PR and confirming the gate blocks it.

**Verification steps.** Push a branch with a knowingly broken layer import; confirm
CI fails on `lint-imports` and the merge is blocked. Revert; confirm green.

---

### M1 — Retired authentication surface persists as unreachable, untested, partly-broken code

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect + spec contradiction |
| **Severity** | Medium |
| **Category** | Architecture / maintainability / security surface |
| **Disposition** | **Needs Product Decision** (PD2) |
| **Release impact** | Does not block; resolve before it is re-exposed |

**Location:** `aimos/saas/auth_service.py:133-436`, `aimos/saas/oauth.py` (199 lines),
`aimos/saas/sms.py` (111 lines), `aimos/saas/router.py:209-212`.

`specs/AIMOS_SaaS_Requirements_and_Task_Tracker.md` §8 marks as complete: "Removed
public registration, Google/Apple OAuth, phone OTP, and forgot-password endpoints."
The **endpoints** are indeed gone. The **implementations** are not:
`register_email_password`, `forgot_password`, `reset_password`,
`send_phone_verification`, `verify_phone_and_login`, `login_with_google`,
`login_with_apple`, `verify_email`, `resend_email_verification`, and the entire
`oauth.py` and `sms.py` modules remain fully wired, importable, and imported at
module load by `auth_service`. `set_auth_cookies` (`router.py:209`) is also dead —
and sets cookies **without `secure=True`**, so re-enabling it would ship auth cookies
over plaintext HTTP.

**Evidence that this code is entirely untested:** `_render_password_reset_email`
(`aimos/saas/email.py:36-43`) returns `text, html` but never assigns `html`:

```
$ python -c "from aimos.saas.email import _render_password_reset_email as f; f('123456','http://x')"
NameError : name 'html' is not defined
```

A `NameError` on the happy path of a security-relevant function survives in a
repository with 466 passing tests — which is direct proof that no test, and no
runtime path, reaches this code.

**Impact.** Dead code with `AuthError`-raising security semantics is a latent
re-exposure risk: anyone re-mounting these functions gets unauthenticated public
registration (`register_email_password` creates users and issues tokens with no
authorization check) on a single-admin system, plus a broken reset flow, plus
unthrottled endpoints (H3). It also directly contradicts a spec marked complete,
which erodes the spec's reliability as the audit's source of truth.

**Recommended solution.** Answer PD2, then either delete `oauth.py`, `sms.py`, and
the retired `auth_service` functions along with the `Authlib` dependency
(`pyproject.toml:46`) and the now-unused ORM models — or, if retained deliberately,
fix the `NameError`, add `secure=True` to `set_auth_cookies`, mark the module
clearly, and add tests. Deletion is recommended: it removes ~350 lines of
security-sensitive unreachable code and one dependency.

**Verification steps.** After deletion: `python -m pytest`, `lint-imports`, and a
grep confirming no remaining references. Confirm the app still boots with SaaS
enabled and login still works end to end.

---

### M2 — Admin password must persist in plaintext configuration and is re-hashed on every boot; no change path

| Field | Value |
|---|---|
| **Classification** | Design Concern |
| **Severity** | Medium |
| **Category** | Security — credential lifecycle |
| **Disposition** | Open — Required Before Release |

**Location:** `aimos/saas/auth_service.py:524-526`

```python
else:
    # Keep the configured password in sync so operator resets work.
    user.password_hash = hash_password(cfg.admin.password)
```

The admin password is re-hashed from configuration on **every** boot. Consequences:
the plaintext must remain in `config/saas.yaml` or `AIMOS__SAAS__ADMIN__PASSWORD`
permanently; there is no password-change endpoint or UI (G2), so the config file *is*
the credential store; and any out-of-band change is silently reverted on restart.

`config/saas.yaml` is mounted read-only into the container
(`docker-compose.yml:22`) and `.gitignore` was checked — the real config is not
committed, and no secrets were found in the repository by scan. So this is a design
weakness, not an active disclosure.

**Recommended solution.** Seed from config **only when the user does not exist**;
add a `POST /api/v2/me/password` endpoint (current password + new password, strength-
checked via the existing `is_strong_password`) and a Settings UI section; support an
explicit `AIMOS_ADMIN_PASSWORD_RESET=1` boot flag for genuine lockout recovery.
Revoke all refresh tokens on password change.

---

### M3 — Long-lived refresh tokens stored in `localStorage`

| Field | Value |
|---|---|
| **Classification** | Design Concern |
| **Severity** | Medium |
| **Category** | Security — session management |
| **Disposition** | Scheduled Post-Release |

**Location:** `dashboard/src/api.js:30-45`

30-day refresh tokens (`refresh_token_expire_days: 30`) are held in `localStorage`,
readable by any JavaScript in the origin. The `httpOnly` cookie path exists but is
dead code (M1). Access-token lifetime is a sensible 15 minutes, and token rotation on
refresh is correctly implemented (`auth_service.py:463-476`) — good practice that
limits the window.

Severity is Medium rather than High because the XSS prerequisite is not currently
demonstrated: React escapes by default, and no `dangerouslySetInnerHTML` exists in
the dashboard (verified by search). The residual concern is a stored-XSS path via
attacker-influenced content — the AI analyst renders LLM output, which is the most
plausible sink and is worth a focused review.

**Recommended solution.** Move the refresh token to an `httpOnly; Secure; SameSite=Strict`
cookie (repairing `set_auth_cookies` with `secure=True`), keep the access token in
memory only, and add a strict `Content-Security-Policy` response header. No security
headers are currently set on any response — `X-Content-Type-Options`,
`X-Frame-Options`/`frame-ancestors`, and `Referrer-Policy` should be added alongside.

---

### M4 — Admin seeding failures are silently swallowed; no authentication audit trail

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | Medium |
| **Category** | Observability / operations |
| **Disposition** | Open — Required Before Release |

**Location:** `aimos/saas/db.py:43-49`

```python
try:
    from aimos.saas import auth_service
    with _SessionLocal() as session:
        auth_service.ensure_admin_user(session)
except Exception:
    pass
```

A bare `except Exception: pass` with no logging. If admin seeding fails — bad config,
DB permissions, Postgres unreachable — the application starts **successfully** with
no admin user and no diagnostic whatsoever. The operator sees a login form that
rejects correct credentials, with nothing in the logs to explain why.

Relatedly, there is **no audit trail for authentication events** (G3): no log entry
for successful login, failed login, token refresh, logout, or exchange-key change.
Control actions *are* journaled with `source="ui"` (`aimos/api/server.py` docstring,
verified), so the pattern exists — it simply was not applied to auth.

**Recommended solution.** Log the exception (`log.exception("admin_seed_failed")`) and
re-raise when `saas.enabled` is true — failing to create the only account in an
auth-enabled system is a fatal misconfiguration, not something to continue past. Add
structured events for the auth lifecycle, and surface repeated failures via the
existing Telegram alerting (G7).

---

### M5 — Unbounded `limit` parameter on decision queries

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | Medium |
| **Category** | Performance / availability |
| **Disposition** | Scheduled Post-Release |

**Location:** `aimos/api/server.py:139-141`, `aimos/api/server.py:79-85`

`GET /api/decisions?limit=` accepts any integer and passes it to
`... ORDER BY seq DESC LIMIT ?`. `?limit=100000000` loads and JSON-serializes the
entire journal into memory. Unauthenticated in default config (H1). The SQL itself is
correctly parameterized — no injection risk — and all other journal queries use bound
parameters (verified across `aimos/journal/journal.py` and `serve.py`).

**Recommended solution.** `limit: int = Query(50, ge=1, le=500)`. Apply the same bound
to `_assistant_decisions` (`serve.py:371`), which is already internally capped at 40
but takes a parameter.

---

### M6 — `/metrics` requires authentication in SaaS mode, breaking Prometheus scraping

| Field | Value |
|---|---|
| **Classification** | Design Concern |
| **Severity** | Medium |
| **Category** | Observability |
| **Disposition** | Needs Product Decision |

**Location:** `aimos/api/server.py:111` (exemption list), `335-338`

Confirmed in the C2 repro: `GET /metrics` → 401 when SaaS is enabled. Prometheus
cannot present a bearer token without additional configuration, so enabling auth
silently breaks metrics collection. Conversely, leaving it public exposes decision
counts.

There is also **no health, readiness, or liveness endpoint anywhere** (G4) — despite
`restart: unless-stopped` and a watchdog service in `docker-compose.yml`. Container
orchestration cannot distinguish "process up" from "trading loop alive". The
heartbeat file that the watchdog consumes is not exposed over HTTP.

**Recommended solution.** Decide per PD: either configure the scraper with a static
token, or bind `/metrics` to a separate internal port. Separately, add `GET /healthz`
(liveness — process responds) and `GET /readyz` (readiness — journal writable, loop
heartbeat fresh) as public endpoints, and wire them into the compose healthcheck.

---

### M7 — GPL-origin files are tracked; distribution is blocked until rewritten

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect (licensing) |
| **Severity** | Medium |
| **Category** | Legal / compliance |
| **Disposition** | **Needs Product Decision** (PD3) |

**Location:** `vendor/ft_protections/__init__.py`, `aimos/universe/filters.py`
(`VolatilityFilter`)

```
$ python scripts/check_gpl_tripwire.py
⚠️  GPL TRIPWIRE: 2 GPL-origin file(s) tracked.
    Private use is fine; REWRITE these clean-room before ANY distribution:
```

The project's own tripwire is armed and correct. `README.md` states "Private project",
so current use is compliant. This becomes blocking the moment AIMOS is distributed,
sold, or offered as a hosted service.

Note the tripwire **exits 0** while printing the warning, so it cannot function as a
CI gate as written (relates to H5). If it is intended to block distribution builds it
must exit non-zero, or CI must grep its output.

**Recommended solution.** Answer PD3. If distribution is ever contemplated,
clean-room reimplement both from specification rather than source, and record the
process in `vendor/VENDOR.md`.

---

### L1 — `specs/STATUS.md` test count is stale

**Classification:** Confirmed Defect · **Severity:** Low · **Disposition:** Open — Required Before Release

`specs/STATUS.md:28` states "465 tests collected, all green (one xfail)". Measured:
**466 passed, 1 xfailed**. Trivial drift, but STATUS is designated the single source
of truth and is the first file every contributor reads.

---

### L2 — Documented install command fails against a Debian-patched system Python

**Classification:** Probable Risk · **Severity:** Low · **Disposition:** Accepted Risk / document

`README.md:88` documents `pip install -e '.[dev,data,serve]'`. Against this
container's Debian system interpreter (pip 24.0, setuptools 68.1.2) it fails:

```
Building wheel for ta (setup.py): finished with status 'error'
AttributeError: install_layout. Did you mean: 'install_platlib'?
ERROR: Could not build wheels for ta
```

`ta==0.11.0` ships as an sdist with no wheel and breaks against Debian's patched
setuptools. In a clean virtualenv with current `pip`/`setuptools` the same command
**succeeds** (exit 0, verified). `run.sh` already creates a venv, so the supported
path is unaffected — this only bites someone following the README's Development
section against a system Python. Recommend documenting the venv prerequisite
explicitly.

---

### L3 — Go-live gates can be marked out of order

**Classification:** Design Concern · **Severity:** Low · **Disposition:** Scheduled Post-Release

`GoLiveLadder.mark` (`aimos/runtime/golive.py:60-66`) validates only that the gate ID
exists. `scaling` can be marked before `backtest_validated`. Since `live_allowed`
requires **all** gates, this does not weaken the final guarantee — the ladder is
fail-closed on completeness, which is the property that matters. It does allow the
progress display to misrepresent readiness. Recommend enforcing sequential
prerequisites, or at minimum surfacing out-of-order sign-offs in the UI.

---

### L4 — User enumeration via timing on the login endpoint

**Classification:** Probable Risk · **Severity:** Low · **Disposition:** Accepted Risk

`send_login_otp` (`auth_service.py:557-561`) returns early for an unknown email
without performing a bcrypt comparison, while a known email costs ~275 ms. The
timing difference reliably reveals whether an address is the admin's. Impact is
minimal here: there is exactly one account and its address is operator-chosen
configuration, not a discoverable user list. Standard mitigation is a dummy bcrypt
comparison on the not-found path.

---

## Remediation Plan

### Group 1 — Immediate release blockers

| Order | ID | Work | Depends on |
|---|---|---|---|
| 1 | **C1** | Containment check on the SPA route; rotate `.jwt_secret` and `.settings_key`; rotate exchange keys | — |
| 2 | **C2** | Fix middleware public-path logic so the SPA and assets load | **Must follow C1** — otherwise the traversal becomes reachable unauthenticated in SaaS mode |
| 3 | **H2** | Stop logging the OTP body; gate `_dev_drop` behind a dev flag; purge `state/maildrop` and logs | Independent, but closes the second 2FA-bypass path opened by C1 |
| 4 | **H1** | Mandatory auth (or loopback-only) for control endpoints; default `AIMOS_HOST` to `127.0.0.1` | C2 (shared middleware) · PD1 |
| 5 | **H3** | OTP attempt cap + `/auth/*` throttle + failed-login logging | Schema change to `EmailLoginCode` |

**Ordering rationale:** C1 first, because it defeats every other authentication
control and its key material must be rotated before anything else is trusted. C2
second and strictly after C1. H2 can proceed in parallel.

### Group 2 — Required pre-release

| ID | Work |
|---|---|
| **H4** | Backup script + schedule + retention; make `restore_drill.sh` fail without a backup; back up `state/.settings_key` securely |
| **H5** | CI pipeline running all four gates + dashboard build + `pip-audit` + secret scan; block merges on failure |
| **M2** | Password-change endpoint + UI; seed from config only on first run |
| **M4** | Log and re-raise admin-seed failures; add auth-event audit logging |
| **M6** | Add `/healthz` and `/readyz`; decide `/metrics` exposure |
| **M8** | Atomic writes for `state.json`/`go_live.json`; resilient loader; `.bak` for go-live |
| **L1** | Correct the STATUS test count |

### Group 3 — Short-term post-release

| ID | Work |
|---|---|
| **M1** | Delete (or repair and test) the retired auth surface; drop `Authlib` — pending PD2 |
| **M3** | Refresh token to `httpOnly; Secure` cookie; add CSP and security headers |
| **M5** | Bound the `limit` query parameter |
| **L3** | Sequential go-live gate prerequisites |
| **L5** | Add `<html lang="en">`; run a full keyboard/contrast/screen-reader a11y audit |
| **G5/G7** | Session listing + global revoke; alert on repeated failed logins |

### Group 4 — Long-term architectural

| Item | Rationale |
|---|---|
| **Adopt a migration framework** (Alembic) for the auth/settings DB | `Base.metadata.create_all` cannot alter existing tables; H3 already needs a column. Without this, every schema change is a manual drop-and-recreate — untenable once the DB holds anything durable. |
| **Separate the API process from the trading loop** | Today one process serves HTTP and runs trading. H3's CPU-exhaustion impact exists *because* of this coupling; separation converts a trading outage into a UI outage. |
| **Move key material outside the working directory** | Structural defense against the whole class of bug C1 belongs to. |
| **Decide the multi-tenant question and commit** (PD2) | The half-retired model taxes every change to the auth layer. |
| **Browser-based E2E + accessibility testing** | The dashboard is 21 screens with zero browser-level test coverage. |

### Cross-cutting regression risks

- **Auth changes (C2, H1, H3) all touch the same middleware.** Land them in one
  reviewed sequence with the full endpoint matrix re-tested, not as independent
  patches.
- **Key rotation invalidates all sessions** and makes existing encrypted exchange
  credentials undecryptable — plan the operator's re-entry step explicitly.
- **The four quality gates must be re-run after every fix**; H5 should land early so
  the remaining fixes are gate-protected.

---

## Residual Risks and Final Checklist

### Accepted and deferred risks

| Risk | Disposition | Owner decision |
|---|---|---|
| GPL-origin files block distribution | Accepted while private | PD3 |
| Timing-based user enumeration (L4) | Accepted — single known account | — |
| Search/filter/export gaps | Deferred — not needed for a single-operator monitor | — |
| `ta` sdist build on system Python (L2) | Accepted — `run.sh` uses a venv; document it | — |
| Out-of-order go-live sign-off (L3) | Deferred — final guarantee unaffected | — |

### Unverified concerns

- ~~**Stored-XSS via AI analyst output**~~ — **Resolved in Pass 2.** No
  `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function` exists anywhere
  in `dashboard/src` (verified by search + live render with 0 console errors). React's
  default escaping is intact, so the realistic injection path for M3 does not exist.
  M3 (refresh token in `localStorage`) remains a valid hardening item but its
  exploitability is now low.
- **Postgres/TimescaleDB paths** — the compose deployment points the auth DB and
  time-series store at Postgres; all testing here used SQLite. Concurrency, type
  mapping (`JSON` columns in `user_settings`), and migration behavior are unverified.
- **Telegram command authorization** — `aimos/telegram/` has a nonce flow that was
  read but not exercised; it is a second control channel into the same runtime.
- **Live and testnet execution paths** — dormant by design; `LiveBroker` and
  `MultiVenueLiveRouter` are mock-tested only.
- **Rolling deployment / concurrent instances** — `SettingsStore._key` is a
  process-level class cache and `state/*.json` files are written non-atomically; two
  instances sharing a volume were not tested and are a plausible corruption source.
- **Watchdog behavior** — restart-on-heartbeat-miss was not exercised.

### Missing environments, credentials, and evidence

- No exchange API keys (testnet or live) → the entire live path is unvalidated
  against a real venue. `specs/TESTNET.md` documents the procedure; it has not been run.
- ~~No Node toolchain~~ → **Corrected in Pass 2.** Node 22 is available at
  `/opt/node22`; the dashboard was built and rendered in Chromium. Remaining UI gap
  is a per-screen UX/accessibility walkthrough, not "no browser at all".
- No production environment, log aggregator, monitoring stack, or backup artifact.
- No `ANTHROPIC_API_KEY` → the AI analyst path is untested at runtime.

### Required testing before release

| Type | Status | Notes |
|---|---|---|
| Manual E2E of the login flow | **Required** | Cannot pass until C2 is fixed |
| Browser testing of all 21 screens | **Required** | Never performed |
| Accessibility audit (keyboard, screen reader, contrast, focus) | **Required** | Never performed; no a11y tests exist |
| Responsive / mobile testing | **Required** | Never performed |
| Load testing of the API and trading loop | **Required** | Directly relevant to H3 |
| Penetration testing | **Recommended** | Re-test C1 and the auth surface after fixes |
| Backup restore drill | **Required** | Cannot pass until H4 is implemented |
| Testnet validation run | **Required before live only** | `specs/TESTNET.md` |

### Readiness checklist

| Area | Status | Evidence |
|---|---|---|
| Architecture & layering | **Pass** | `lint-imports` 6/6 kept, 167 files analyzed |
| Determinism / no-LLM-in-decision-path | **Pass** | magic-number lint clean; `vt_research` import forbidden and kept |
| Time handling | **Pass** | naive-datetime lint clean |
| Unit / integration tests | **Pass** | 466 passed, 1 xfailed |
| Test coverage of the auth↔SPA interaction | **Fail** | C2 shipped undetected; `NameError` in M1 undetected |
| Journal integrity | **Pass** | SHA-256 chain, `verify()` implemented and tested |
| Live-trading fail-closed design | **Partial** | Three locks correctly implemented and `LOCKED` flags verified; ladder sign-off is writable unauthenticated (H1) |
| Authentication | **Fail** | C1, C2, H2, H3 |
| Authorization | **Fail** | H1 — no authz in default config |
| Tenant isolation | **Not Applicable** | Single-operator product by design |
| Secret handling | **Fail** | H2; keys readable via C1. Encryption at rest and UI redaction are correct. |
| Input validation | **Pass** | Pydantic models throughout; SQL fully parameterized |
| Rate limiting | **Fail** | H3 — none inbound |
| Security headers / CSP | **Fail** | None set |
| Database constraints & migrations | **Partial** | ORM constraints present; **no migration framework** |
| Backups & restore | **Partial** | H4 fixed — `backup_journal.py` (verified snapshots) + honest drill; scheduling at target RPO is the remaining ops step |
| CI/CD & quality gates | **Partial** | H5 fixed — `.github/workflows/ci.yml` runs all gates + dashboard build; awaiting one green run on the runner |
| Health / readiness probes | **Fail** | G4 — none |
| Logging & metrics | **Partial** | structlog + `/metrics`; no auth audit trail (M4); secrets logged (H2) |
| Alerting | **Partial** | Telegram alerts exist; no security alerting |
| Deployment & rollback | **Partial** | Dockerfile + compose + watchdog; no artifact versioning, no documented rollback (M8 restart-recovery gap now fixed) |
| Dependency & secret scanning | **Not Tested** | No tooling configured |
| UI / UX | **Partial** | Pass 2: dashboard builds and renders — 21 screens, 41 assets, live data, **0 console errors**, all controls labeled. Full UX walkthrough of each screen still pending |
| Accessibility | **Partial** | Pass 2 automated probe: 0 unlabeled inputs/buttons (good); **1 defect** — missing `<html lang>` (L5). Keyboard/focus/contrast/screen-reader audit still required |
| Performance & load | **Not Tested** | No load testing performed (H3 is the priority target) |
| Data durability | **Partial** | M8 fixed — atomic writes + resilient loaders + go-live `.bak`; journal backups now exist (H4). Live-DB restore at scale still unverified |
| Licensing | **Partial** | Tripwire armed (M7); fine while private |

---

## Stopping-Rule Assessment

| Rule | Met | Basis |
|---|---|---|
| 1. No open Critical findings | **No** | C1, C2 |
| 2. No release-blocking High findings | **No** | H1–H5 |
| 3. Critical journeys pass end to end | **No** | Login cannot complete with auth enabled (C2) |
| 4. Auth / authz / secrets verified | **No** | Verified as *failing* |
| 5. Build, test, migration, deploy, monitoring, backup, rollback gates pass | **No** | No CI, no backups, no migrations, no health probes |
| 6. Product gaps resolved or formally deferred | **Partial** | G1 open; PD1–PD5 outstanding |
| 7. Remaining risks have owner and disposition | **Partial** | Documented; ownership pending |
| 8. Two consecutive passes with no new Critical/High | **Partial** | Pass 2 added **no** new Critical/High (only M8, L5) — first of the two required clean passes is now on record; a post-fix pass is still needed |
| 9. Remaining findings mainly low-risk | **No** | C1/C2 + H1–H5 open |
| 10. Another pass unlikely to change the decision | **Partial** | Pass 2 did not change the decision; it hardened the evidence and shrank the untested surface. The decision will not flip until C1/C2 + H1–H5 are fixed |

**Pass 2 conclusion.** A second broad pass surfaced no new release-blocking findings —
only one Medium (M8) and one Low (L5) — and instead firmed up the existing evidence
(C1 kill chain proven; XSS sink absence and the Telegram channel verified; the UI
rendered and probed). Per stopping rule 8, that is the expected trajectory: the
Critical/High set has stabilised at C1, C2, H1–H5. **Further general audit passes are
not warranted before remediation** — the next pass should be a *targeted
verification* pass after the blockers are fixed, with the objective already
enumerated above.

**Objective for the next audit pass** — not a general re-audit:

1. Re-test C1 with the full encoded-traversal matrix; confirm both keys were rotated.
2. Confirm the SaaS-mode login journey end to end in a **real browser** with a built
   `dashboard/dist`.
3. Verify `/api/*` still 401s without a token after the C2 fix (no over-broad exemption).
4. Verify the OTP attempt cap and `/auth/*` throttle by execution.
5. Verify a backup exists, verifies, and that the drill **fails** without one.
6. Confirm CI blocks a deliberately-failing commit.
7. Review the AI analyst render path for stored XSS (the open unverified concern).
8. Exercise the Postgres/TimescaleDB deployment at least once.

---

## Pass 2 Addendum — Live-Server Execution

Pass 2 closed Pass 1's two largest scope gaps: a Node toolchain **is** available
(`/opt/node22`, just not on the default PATH — a Pass 1 error, corrected here), and
Chromium is preinstalled. The dashboard was built and the real application was run
and exercised. Summary: **no new Critical or High findings**; C1 upgraded to a proven
end-to-end kill chain; two lower-severity findings added; several Pass 1 "Not Tested"
and "Unverified" items resolved.

### What was newly verified

| Pass 1 status | Pass 2 result |
|---|---|
| C1 shown on a replica | **Confirmed on the live server** + forged-admin-token kill chain proven (see C1) |
| UI — Not Tested (no browser) | **Dashboard renders**: all 21 nav screens, 41 assets, live data, **0 console errors**, 0 unlabeled inputs/buttons |
| M3 stored-XSS — Unverified | **No XSS sink exists** — zero `dangerouslySetInnerHTML`/`innerHTML`/`eval` across all dashboard source. M3 residual risk substantially reduced (token-in-`localStorage` remains, but the realistic injection path does not) |
| Telegram control channel — Unverified | **Verified as a strength** — chat allowlist (unknown → silent ignore + log), two-step nonce for dangerous commands, wrong-chat confirm rejection, 60s TTL, no cap-raising. Stronger than the HTTP API's auth story |
| H1 — control API open by default | **Visually confirmed** — the full dashboard and all trading data load at `/` with no login gate in default mode |

### Screenshot evidence

The rendered Markets screen (paper mode): header shows `Equity $10687 · Decisions
1680 · NO_TRADE rate 92% · Mode paper · single-user`, a 21-item navigation bar, and
a 41-row live decision table (regime, p_up, confidence, opportunity, risk, action).
The UI is polished and professional. Crucially, **no authentication was required to
reach it** — direct evidence for H1.

---

### M8 — Runtime state and go-live files are written non-atomically; a torn write crashes boot or silently wipes go-live sign-offs

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect |
| **Severity** | Medium |
| **Category** | Data integrity / durability / availability |
| **Disposition** | **Fixed — Awaiting Verification** (atomic writes + resilient loaders — see *Remediation Applied*) |
| **Release impact** | Was a durability gap; fixed |
| **Likelihood** | Medium — triggered by any unclean shutdown mid-write |

**Location:** `aimos/runtime/state_store.py:60-61`, `aimos/runtime/golive.py:50-52`

```python
# state_store.py — truncates the file, THEN writes; no temp-file + rename
with self.file_path.open("w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2, default=str)
```

```python
# golive.py
self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
```

**Root cause.** Both persist JSON by truncating the target file and writing in place,
with no write-to-temp-then-`os.replace` (which is atomic on POSIX). If the process
dies mid-write — and the bundled `watchdog` (`docker-compose.yml`) restarts the app
on 3 missed heartbeats, plus OOM kills and `docker stop` during a rolling deploy all
apply — the file is left truncated. The two loaders then diverge:

- `RuntimeStateStore.load` (`state_store.py:39-42`) calls `json.load` with **no
  error handling** → boot crashes with `JSONDecodeError` and stays down until an
  operator manually deletes `state.json`.
- `GoLiveLadder._load` (`golive.py:42-48`) **swallows `ValueError`** and returns
  `{"gates": {}, "markers": {}}` → all operator go-live sign-offs and the paper-day
  markers are **silently discarded**.

**Evidence — reproduced by execution (Pass 2).**

```
state_store.load(torn): CRASHES -> JSONDecodeError: Unterminated string ...
   (RuntimeStateStore.load has NO try/except around json.load -> boot fails)

go_live before torn write: live_allowed=True (all 6 gates signed off)
go_live after torn write:  live_allowed=False passed=0/6
   (golive._load swallows ValueError -> ALL operator sign-offs silently wiped)
```

**Impact.** The go-live reset is fail-*safe* on the money axis (it resets toward
"not allowed", never toward "allowed"), so it does not risk premature live trading —
but it silently destroys the operator's go-live record and resets the `paper_4wk`
timeline with no warning, which erodes trust in the ladder (compare H4). The
state-store boot crash is the sharper edge: a single unclean shutdown makes the
application **fail to start** until someone hand-edits the state directory — poor
behavior for a system with an auto-restart watchdog, since the watchdog will
restart it straight back into the same crash.

**Recommended solution.** Write atomically and make the loader resilient.

```python
# atomic write helper (illustrative)
import os, tempfile
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=str)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)          # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

And in `RuntimeStateStore.load`, wrap `json.load` in `try/except (ValueError,
OSError)` returning `{}` (matching the resilient go-live loader), and log a warning
so a discarded snapshot is at least visible rather than silent. For go-live,
atomic-write plus a `.bak` of the last-good file is worth it given the value of the
sign-off record.

**Regression risks.** `os.replace` across filesystems fails — keep the temp file in
the same directory (as above). `fsync` adds latency to each save; the save cadence
here is per-tick-batch, not per-tick, so the cost is acceptable.

**Tests to add.** `test_state_store_survives_torn_write` (write partial JSON, assert
`load()` returns `{}` and logs, does not raise); `test_golive_atomic_write_survives_kill`
(assert a torn temp never replaces the good file); `test_atomic_write_leaves_no_tmp`.

**Verification steps.** Populate `state.json`; truncate it to a partial object;
start the server → must boot (not crash). Sign off all go-live gates; truncate
`go_live.json`; reload → sign-offs preserved from the `.bak`, or at minimum a logged
warning rather than a silent reset.

**Similar locations inspected.** `serve.py:282` (monitor report),
`watchdog.py:32` (heartbeat), and `settings.py:158` (`.jwt_secret`) use the same
in-place write. The heartbeat is transient (self-heals next tick) and the JWT secret
is write-once, so neither is impactful; the monitor report is display-only. Applying
the atomic helper uniformly is the clean fix. The SQLite journal and auth DB are
**not** affected — SQLite manages its own durability.

---

### L5 — `<html>` element has no `lang` attribute (WCAG 3.1.1)

| Field | Value |
|---|---|
| **Classification** | Confirmed Defect (accessibility) |
| **Severity** | Low |
| **Disposition** | **Verified** (`<html lang="en">` added; confirmed in-browser) |

**Location:** `dashboard/index.html:1`

```html
<!doctype html><html><head><meta charset="utf-8"><title>AIMOS</title></head>
```

**Evidence.** Confirmed in the live render (`html[lang]: None`) and in source. No
`lang` attribute is set, so screen readers cannot select the correct pronunciation
rules. WCAG 2.1 Level A, SC 3.1.1 (Language of Page).

**Recommended solution.** `<html lang="en">`. Trivial.

**Other a11y observations (Pass 2, positive).** The browser probe found **0** inputs
without a label/aria-label/placeholder and **0** buttons without an accessible name —
a good baseline. A full audit (keyboard traversal, focus-visible, colour contrast on
the badge colours, screen-reader flow) is still required before release (see
Residual Risks); this finding is the one concrete defect surfaced by the automated
probe.

---

## Remediation Applied (this branch)

Source-code changes were authorized after Pass 2. The fixes below were implemented,
tested, and — for the Criticals — verified against a live running server. **No
decision-path/layer rules were touched**: magic-number lint, naive-datetime lint,
and import-linter (6/6) remain green; the suite grew from 466 to **483 passed / 1
xfailed** with 17 new regression tests.

| Finding | Disposition | Fix | Tests | Live verification |
|---|---|---|---|---|
| **C1** traversal | **Verified** | `serve.py` SPA route now resolves the candidate and requires `is_relative_to(DIST)`; falls back to the SPA shell otherwise | `test_saas.py::TestSpaTraversalBlocked` | `curl` of `…/state/.jwt_secret`, `…/config/mandate.yaml`, `…/CLAUDE.md` all return the SPA shell, not the file; legit asset still 200 |
| **C2** SPA lockout | **Verified** | `server.py` middleware exemption rewritten (`_is_public_path`): SPA shell + assets public, `/api/*` and `/metrics` protected | `test_saas.py::TestSpaReachableWhenSaasEnabled` (5) | With SaaS on: `/`, `/login`, `/assets/*`, `/api/v2/status` → 200; `/api/decisions`, `/metrics` → 401. **Login page renders in Chromium** ("Sign in… Email / Password / Send login code") |
| **H1** open control API | **Fixed — Awaiting Verification** | Default `AIMOS_HOST` → `127.0.0.1`; control + assistant endpoints refuse non-loopback callers when SaaS is off (`_is_control_path` + `_client_is_local`) | `test_saas.py::TestControlPathGuards` (3) | Loopback `POST /api/control/pause` → 403 confirm-gate (allowed through, still gated). Remote-block path unit-tested, not exercised from a second host |
| **H2** OTP logged/dropped | **Fixed — Awaiting Verification** | `email.py`/`sms.py`: no body in the no-SMTP log; `_dev_drop` gated behind `AIMOS_DEV_MAILDROP`, files `0600`. Also fixed the `_render_password_reset_email` `NameError` | `test_saas.py::TestOtpNotLeaked` (2) | — |
| **H3** no auth throttle | **Fixed — Awaiting Verification** | `EmailLoginCode.attempts` column + burn-after-`MAX_OTP_ATTEMPTS` (5); per-IP fixed-window throttle on `/auth/*` (429) | `TestOtpBruteForceBounded`, `TestAuthThrottle` | — |
| **M8** torn state writes | **Fixed — Awaiting Verification** | New `runtime/atomic_io.py` (temp+fsync+`os.replace`); `state_store.load` catches torn JSON; `golive` keeps a `.bak` and restores it | `test_runtime_state.py` (2), `test_golive.py` (2) | — |
| **H4** no backups | **Fixed — Awaiting Verification** | New `scripts/backup_journal.py` (SQLite online-backup API + immediate hash-chain verify + retention + atomic `journal-latest` pointer); `restore_drill.sh` now **exits 1** when no backup exists | `test_backup_journal.py` (5) | CLI: verified snapshot created; drill exits 1 with no backup, 0 with one |
| **H5** no CI | **Fixed — Awaiting Verification** | New `.github/workflows/ci.yml`: pytest + all three lints + GPL tripwire + backup/restore drill, plus a dashboard-build job; runs on every push/PR | (workflow) | Not yet exercised on the CI runner (no push observed in this session) |
| **L5** missing `<html lang>` | **Verified** | `dashboard/index.html` → `<html lang="en">` | (static) | Chromium reports `html[lang]="en"` |

**H1 note.** The loopback guard and loopback-default host close the *accidental*
exposure and the anonymous-remote-control path. Whether H1 is fully retired or
downgraded to Accepted Risk still depends on **PD1** (is AIMOS ever exposed beyond
localhost/an authenticated proxy?) — that product decision is unchanged by the fix.

**Files changed:** `aimos/runtime/serve.py`, `aimos/api/server.py`,
`aimos/saas/email.py`, `aimos/saas/sms.py`, `aimos/saas/auth_service.py`,
`aimos/saas/models.py`, `aimos/runtime/state_store.py`, `aimos/runtime/golive.py`,
`aimos/runtime/atomic_io.py` (new), `scripts/backup_journal.py` (new),
`scripts/restore_drill.sh`, `.github/workflows/ci.yml` (new), `dashboard/index.html`,
and the test files (`test_saas.py`, `test_serve.py`, `test_runtime_state.py`,
`test_golive.py`, `test_backup_journal.py`).

**Now closed:** all seven Critical/High/Medium blockers targeted (C1, C2, H1–H5,
M8) plus L5. Suite 466 → **488 passed / 1 xfailed**.

**Still open (not release-blocking):** the product decisions PD1–PD5 (notably PD1
— the network-exposure model that finalises H1's disposition, and PD3 — GPL/M7
before any distribution); the scheduling of the new backup script at the target
RPO; the H3 schema migration on existing deployments (`email_login_codes` gains an
`attempts` column and there is still no migration framework — a Group 4 item); and
the remaining Mediums/Lows (M1–M7 except the H2 `NameError`, L1–L4). **An
independent verification pass** — by someone other than the fix author — should
re-run the C1/C2 checks and exercise the H1 remote-block, H3 throttle, and the CI
workflow on the runner before these move from *Fixed — Awaiting Verification* to
*Verified*.

**Schema note (H3).** `EmailLoginCode.attempts` is a new column. The project still
has no migration framework (a Group 4 item); on an existing deployment the
transient `email_login_codes` table should be dropped so `create_all` rebuilds it.

---

## Audit Integrity Statement

This audit covers the reviewed scope, available specifications, executed commands,
and documented assumptions above. Findings marked **Confirmed** were reproduced by
execution in this environment; findings marked **Probable Risk**, **Design Concern**,
or **Unverified** were not. Areas listed as Not Tested were not assessed and no
conclusion about them should be drawn from this report.

This report does not claim the application is bug-free, completely secure, or
guaranteed never to fail. Production readiness is assessed only within the scope,
conditions, evidence, assumptions, accepted risks, and limitations documented here.
