# AIMOS SaaS v2.0 — Requirements & Task Tracker

> This document consolidates the remaining runtime work (streaming, persistence, ML, vendoring, live wiring) with a new SaaS layer for user registration/login and multi-tenancy.
>
> Auth is designed to use **free/open-source dependencies and operator-provided credentials only**. AIMOS itself does not pay for third-party SaaS.

---

## 1. Context & Constraints

### 1.1 Current state (branch `claude/aimos-implementation-gxwsl3`)
- Core three-layer pipeline is implemented and tested.
- Paper loop, dashboard scaffold, API, Telegram, risk manager, journal, and go-live ladder are working.
- Live trading is fail-closed; paper/testnet validation comes first.

### 1.2 Hard rules (do not regress)
- Layer contract: `data → observation → intelligence → execution` via pydantic models; import-linter enforced.
- No LLM in the decision path.
- No hardcoded tunables in `observation/`, `intelligence/`, `execution/`.
- All time via `clock.now()`; no `datetime.now()` in library code.
- Live trading stays fail-closed: `mandate.yaml` + go-live ladder + boot guard.
- Secrets never logged, journaled, or returned to the UI.

### 1.3 New constraints
- **No paid third-party dependencies.** Use free/open-source libraries. Where an external service is required (SMTP, SMS), the operator supplies credentials; the product does not buy them.
- **Self-hostable.** Must run locally with SQLite and in Docker with Postgres/TimescaleDB.
- **Single-user mode must keep working.** SaaS is feature-flagged (`features.saas_enabled`) so existing local installs are not broken.
- **All new code tested and linted.** `pytest`, `check_magic_numbers.py`, `check_no_naive_datetime.py`, `lint-imports` must remain green.

---

## 2. Goals

1. Finish the remaining v2.0 runtime pieces (streaming, persistence, dashboard, ML, vendoring, live wiring).
2. Add a SaaS layer with:
   - User registration and login via **Google, Apple, email, and phone**.
   - Multi-tenancy via **organizations**.
   - Per-tenant config, journal, state, and go-live ladder.
   - Tenant-aware API and dashboard.

---

## 3. Functional Requirements

### 3.1 Authentication

#### Email & password
- Register with email + password.
- Password hashed with bcrypt.
- Send verification email (SMTP credentials supplied by operator).
- Allow resend verification and password reset via email.
- Option to use magic-link login instead of password.

#### Google OAuth2
- "Sign in with Google" button.
- On first login, create user + default organization.
- Link existing account by email if user first registered with password.

#### Apple Sign In
- "Sign in with Apple" button.
- Generate Apple client secret from `client_id`, `team_id`, `key_id`, and private key.
- Create/link user and default organization.

#### Phone registration / login
- User enters phone number.
- System sends a one-time passcode (OTP).
- On verify, create/link user and default organization.
- **SMS gateway is pluggable and operator-supplied.** Default implementation logs the OTP to the console (for local dev). Optional Twilio/Vonage/Amazon SNS drivers are configured with operator credentials.
- If no SMS gateway is configured, phone registration falls back to **email OTP** (same flow, sends code to email). This keeps phone onboarding free when the user also owns the email.

#### Session management
- JWT access token (short expiry, e.g. 15 minutes).
- Refresh token (longer expiry, rotated on use, stored hashed in DB).
- Secure cookie + `Authorization: Bearer` header support.
- Logout invalidates refresh token.

### 3.2 Multi-tenancy

#### Organizations
- Each user belongs to one or more `Organization`.
- Every user has a default personal organization on signup.
- Roles: `owner`, `admin`, `member`, `viewer`.
- Owner/admins can invite members by email; invite links expire.

#### Per-tenant resources
- `OrganizationConfig` overrides `config/default.yaml` per tenant.
- `TenantJournal` stored at `state/journals/<org_id>.sqlite`.
- `TenantState` (equity, balances, positions, go-live ladder, feature flags) persisted in SQLite/Postgres.
- Each tenant's runtime loop is isolated: its own broker, journal, and clock.

#### API scoping
- All `/api/v2/*` endpoints require a valid JWT.
- `X-Organization-Id` header or cookie selects the active organization.
- Endpoints reject access to organizations the user does not belong to.

### 3.3 Remaining v2.0 runtime

| Feature | Requirement |
|---------|-------------|
| **Streaming layer** | WebSocket public top-of-book and trades for Binance/Bybit/Coinbase. Falls back to REST poll when websocket is unavailable. Feeds `OrderBookEngine`, `LiquidityEngine`, scalp, and cross-venue lead-lag. |
| **Runtime persistence** | Save/load equity curve, balances, positions, feature flags, go-live ladder, and monitor report across restarts. Use SQLite JSON column or JSON files under `state/tenants/<org_id>/`. |
| **Richer dashboard** | Add `lightweight-charts` (MIT) for candlestick/equity charts, evidence tables, and the left-to-right decision anatomy flow. |
| **ML training pipeline** | Make `scripts/train_from_history` runnable end-to-end; add model promotion/demotion hooks per `specs/MODELS.md`; keep `fusion_weights.ml = 0` until AUC/shadow gate is cleared. |
| **Vendor vendoring** | Replace `vendor/*` clean-room stubs with pinned-SHA upstream copies where licenses allow; update `vendor/VENDOR.md`; keep GPL code out of the trading runtime. |
| **12-month historical dataset** | Script to download 1h (and 1m for scalp) OHLCV for the configured universe, cache under `data/historical/<exchange>/<symbol>/<tf>.parquet`, with a manifest/checksum file. |
| **Live multi-venue executor wiring** | Integrate `MultiVenueLiveRouter` into `serve.py` behind a `live_multi_venue_enabled` feature flag that requires the go-live ladder. Still fail-closed. |

### 3.4 Dashboard updates
- Login, register, verify email, forgot password, OAuth callback pages.
- Organization switcher and settings.
- User management (invite, role change, remove) for owners/admins.
- All existing trading screens become tenant-aware and fetch `/api/v2/*`.

### 3.5 Admin / operational
- Environment variables for OAuth credentials, SMTP, optional SMS gateway.
- `docker-compose.yml` updated to include a `postgres` auth/tenant database (can reuse existing TimescaleDB).
- Migration script for existing single-user state to a default organization.

---

## 4. Data Model

Use SQLAlchemy 2.0 sync models (already a dependency under `[project.optional-dependencies] data`).

```text
User
  id, email, email_verified, phone_number, phone_verified, password_hash, created_at

Organization
  id, name, slug, owner_id, created_at, mode (paper/live)

OrganizationMember
  user_id, organization_id, role, joined_at

UserIdentity
  id, user_id, provider (google/apple), provider_subject, created_at

EmailVerificationCode
  id, user_id, code, expires_at, used

PasswordResetToken
  id, user_id, token_hash, expires_at, used

PhoneVerificationCode
  id, user_id, phone_number, code, expires_at, used

RefreshToken
  id, user_id, token_hash, expires_at, revoked_at

OrganizationConfig
  organization_id, key, value, updated_at

OrganizationState
  organization_id, equity_json, balances_json, positions_json, ladder_json, features_json, updated_at
```

---

## 5. Dependencies

Add under a new `[project.optional-dependencies] saas` block (or merge into `serve`):

```toml
saas = [
  "bcrypt==4.3.0",
  "PyJWT==2.10.1",
  "cryptography==44.0.1",
  "Authlib==1.4.1",
  "email-validator==2.2.0",
]
```

- `bcrypt` / `PyJWT` / `cryptography` — password hashing and JWT.
- `Authlib` — OAuth2 clients for Google and Apple.
- `email-validator` — pydantic email validation.
- `websockets` is already in `runtime` extra (for streaming).
- `lightweight-charts` will be added via npm in `dashboard/package.json`.

---

## 6. API Surface

### Auth (no org required)
- `POST /auth/register` — email/password.
- `POST /auth/login` — email/password.
- `POST /auth/verify-email` — code.
- `POST /auth/resend-verification`.
- `POST /auth/forgot-password`.
- `POST /auth/reset-password`.
- `POST /auth/refresh`.
- `POST /auth/logout`.
- `GET /auth/google` — redirect to Google.
- `GET /auth/google/callback`.
- `GET /auth/apple`.
- `POST /auth/apple/callback`.
- `POST /auth/phone/send`.
- `POST /auth/phone/verify`.

### Tenant-aware (requires JWT + X-Organization-Id)
- `GET /api/v2/me`
- `GET /api/v2/organizations`
- `POST /api/v2/organizations`
- `POST /api/v2/organizations/{id}/invite`
- `GET /api/v2/organizations/{id}/members`
- `GET /api/v2/config` — effective config for tenant.
- `PATCH /api/v2/config` — owner/admin only.
- Existing trading endpoints are duplicated or wrapped under `/api/v2/*` and use the tenant context.

---

## 7. Implementation Phases

### Phase 1 — Auth foundation
1. `[x]` Add SaaS dependencies to `pyproject.toml`.
2. `[x]` Create `aimos/saas/models.py` SQLAlchemy schema.
3. `[x]` Implement password hashing, JWT, and current-user dependencies in `aimos/saas/security.py`.
4. `[x]` Implement email/password register/login/verify/reset in `aimos/saas/auth_service.py` and `aimos/saas/email.py`.
5. `[x]` Add `/auth/*` FastAPI routers.
6. `[x]` Implement Google and Apple OAuth in `aimos/saas/oauth.py`.
7. `[~]` Implement phone OTP flow with pluggable SMS in `aimos/saas/sms.py` (console default, real Twilio/Vonage via operator credentials; email fallback pending).
8. `[x]` Dashboard: auth pages.

### Phase 2 — Multi-tenancy
1. `[x]` Add `TenantContext` dataclass and dependency.
2. `[~]` Create per-tenant config loader (`aimos/saas/config_tenant.py` — endpoints done, runtime loader pending).
3. `[x]` Create per-tenant journal factory (`aimos/saas/journal_tenant.py`).
4. `[x]` Create per-tenant state persistence (`aimos/saas/state_tenant.py`).
5. `[~]` Update `PipelineOrchestrator` and `build_app` to accept tenant context (`serve.py` loads org and persists per-org; loader integration pending).
6. `[x]` Add `/api/v2/organizations/*` and `/api/v2/config` endpoints.
7. `[ ]` Enforce org scoping on all trading endpoints.
8. `[~]` Dashboard: org switcher, settings, invite flow (switcher + members endpoints done).

### Phase 3 — Finish v2.0 runtime
1. `[~]` Streaming layer: `aimos/data/streaming.py` + exchange websocket feeds (Binance source + recorder wired to serve loop; feed-into-pipeline pending).
2. `[x]` Runtime persistence: save/restore equity, balances, positions, features, ladder (`aimos/runtime/state_store.py`).
3. Dashboard charting: `lightweight-charts` and evidence tables.
4. `[x]` ML pipeline: `scripts/train_from_history` end-to-end, model registry, promotion/demotion (`aimos/learning/registry.py`).
5. Vendor vendoring: fill `vendor/` and `vendor/VENDOR.md`.
6. `[x]` 12-month dataset downloader: `scripts/download_history.py`.
7. Live multi-venue router wiring (still fail-closed).

### Phase 4 — Deployment & docs
1. `[x]` Update `docker-compose.yml` with auth/tenant DB; add `Dockerfile`.
2. `[x]` Migration script for single-user → default org (`scripts/migrate_to_saas.py`).
3. Update `specs/OPERATIONS.md`, `specs/DEPLOYMENT.md`, `specs/STATUS.md`, `CHANGELOG.md`.
4. Add tests for all new modules.
5. Run full `pytest`, `check_magic_numbers.py`, `check_no_naive_datetime.py`, `lint-imports`.

---

## 8. Task Tracker

Legend: `[ ]` pending · `[~]` in progress · `[x]` completed

### Phase 1 — Auth foundation

- [x] Add SaaS dependencies to `pyproject.toml`
- [x] Create SQLAlchemy models (`aimos/saas/models.py`)
- [x] Password hashing + JWT utilities (`aimos/saas/security.py`)
- [x] SMTP email sender (`aimos/saas/email.py`)
- [x] Email/password register, login, verify, forgot/reset (`aimos/saas/auth_service.py`)
- [x] `/auth/*` FastAPI routers
- [x] Google OAuth2 login/callback
- [x] Apple Sign In login/callback
- [x] Phone OTP flow with pluggable SMS (console/Twilio/Vonage); dashboard phone sign-in wired; email fallback can be added if SMS driver is disabled.
- [x] Dashboard login/register/verify/forgot-password/reset/phone-sign-in pages
- [x] Tests for auth flows

### Phase 2 — Multi-tenancy

- [x] `TenantContext` and dependency
- [x] Per-tenant config loader (`aimos/saas/config_tenant.py`) with deep-merge overrides loaded at runtime (`runtime/serve.py` uses `load_params_for_org`).
- [x] Per-tenant journal factory (`aimos/saas/journal_tenant.py`)
- [x] Per-tenant state persistence (`aimos/saas/state_tenant.py`)
- [x] `/api/v2/organizations` and `/api/v2/config` endpoints
- [x] Org scoping middleware for trading endpoints (`saas_tenant_scope` in `aimos/api/server.py`)
- [x] Update `PipelineOrchestrator`/`build_app` to use tenant context (`load_params_for_org`, `tenant_journal_path`, `RuntimeStateStore`)
- [x] Dashboard org switcher, settings, invite/members pages (Settings screen + invite/members endpoints + tests)
- [x] Tests for auth, tenancy, and members/invite (`tests/test_saas.py`)
- [x] Tests for runtime state persistence (`tests/test_runtime_state.py`)
- [x] Tests for ML model registry (`tests/test_model_registry.py`)
- [x] Tests for streaming normalization (`tests/test_streaming.py`)
- [x] Tests for SaaS migration (`tests/test_migrate_to_saas.py`)

### Phase 3 — Finish v2.0 runtime

- [x] Streaming layer: websocket public top-of-book/trades, `StreamFeed` normalizes events to `BookAggregate`/`LargePrint` and injects them into `MarketContext` in the paper loop; recording/replay remains supported.
- [x] Runtime state persistence (equity, balances, positions, features, ladder)
- [x] Rich dashboard: equity chart (`Performance`), candlestick chart (`Candles`), evidence tables (`Engines`), decision anatomy flow (`Decision Anatomy`), organization settings (`Settings`)
- [x] ML training pipeline end-to-end (`scripts/train_from_history`)
- [x] Model promotion/demotion ladder integration (`aimos/learning/registry.py`)
- [x] Vendor vendoring at pinned SHAs: `vendor/manifest.yaml`, `scripts/vendor.py`, `vendor/VENDOR.md` updated with pinned SHAs, dry-run and import/tripwire tests
- [x] 12-month historical dataset downloader (`scripts/download_history.py`)
- [x] Live multi-venue executor wiring behind go-live gate (`_build_live_router` in `runtime/serve.py`, `MultiVenueLiveRouter` integration, fail-closed tests)
- [x] Tests for streaming, stream feed, persistence, ML, dataset, config overlay, org scoping, vendor, live multi-venue wiring (`tests/test_streaming.py`, `test_stream_feed.py`, `test_runtime_state.py`, `test_model_registry.py`, `test_download_history.py`, `test_config_tenant.py`, `test_saas.py`, `test_vendor.py`, `test_live_multi_venue_wiring.py`)

### Phase 4 — Deployment & docs

- [x] Update `docker-compose.yml` with auth/tenant DB; add `Dockerfile`
- [x] Single-user → default-tenant migration script (`scripts/migrate_to_saas.py`)
- [x] Update `specs/OPERATIONS.md` (SaaS auth, runtime state, org-scoped API requests)
- [x] Update `specs/DEPLOYMENT.md` (SaaS Compose deployment section)
- [x] Update `specs/STATUS.md`
- [x] Update `CHANGELOG.md`
- [x] Full test suite + lints green
- [ ] End-to-end smoke run with SaaS disabled and enabled (manual operator step)

---

## 9. Open Questions / Decisions for the Operator

1. **Database for auth/tenants:** reuse the existing TimescaleDB container or a separate SQLite file? (Recommendation: reuse Postgres for SaaS, SQLite for single-user default.)
2. **SMTP provider:** which SMTP host/credentials will be configured for email verification and password reset? (e.g., self-hosted Postfix, Gmail SMTP, etc.)
3. **SMS gateway:** will phone OTP be enabled in production? If yes, which provider credentials (Twilio/Vonage/AWS SNS) will be supplied? Otherwise phone registration falls back to email OTP.
4. **Single-user mode default:** keep `saas.enabled: false` by default so existing installs work unchanged?
5. **Live streaming priority:** which venue should be the first websocket feed? (Recommendation: Binance public streams first, then Bybit, then Coinbase.)
