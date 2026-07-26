# AIMOS Single-Admin Auth & Settings Store — Final Spec

> This document describes the implemented single-user control-plane for AIMOS:
> one admin user seeded from configuration, email-based OTP 2FA, and a
> `SettingsStore` that holds runtime overrides and encrypted exchange API keys.
> The earlier multi-user / multi-tenant SaaS design has been retired.

---

## 1. Context & Constraints

### 1.1 Current state
- Core three-layer pipeline, paper trading, dashboard, journal, go-live ladder,
  and streaming scaffold are implemented and tested.
- Live trading and ML promotion remain fail-closed.
- Auth is reduced to a single admin user; there is no public registration,
  organization switching, or member invites.

### 1.2 Hard rules (do not regress)
- Layer contract: `data → observation → intelligence → execution` via pydantic
  models; import-linter enforced.
- No LLM in the decision path.
- No hardcoded tunables in `observation/`, `intelligence/`, `execution/`.
- All time via `clock.now()`; no `datetime.now()` in library code.
- Live trading stays fail-closed: `mandate.yaml` + go-live ladder + boot guard.
- Secrets never logged, journaled, or returned to the UI.

### 1.3 Design constraints
- **No paid third-party dependencies.** AIMOS itself uses only free/open-source
  libraries. The operator may supply SMTP credentials for the login OTP.
- **Self-hostable.** Runs locally with SQLite and in Docker with Postgres/TimescaleDB.
- **All code tested and linted.** `pytest`, `check_magic_numbers.py`,
  `check_no_naive_datetime.py`, `lint-imports` must remain green.

---

## 2. Goals

1. Provide a single-admin login with email-based one-time-password (OTP) 2FA.
2. Seed the admin user from `config/saas.yaml` or environment variables.
3. Move all runtime configuration into an encrypted `SettingsStore` that the
   dashboard reads/writes through `/api/v2/settings`.
4. Keep YAML files as read-only defaults; the runtime loads overrides and
   exchange keys from the store.

---

## 3. Functional Requirements

### 3.1 Authentication

#### Admin user
- One admin account is created automatically at startup from configuration.
- Config source: `config/saas.yaml` `admin.*` or env vars:
  - `AIMOS__SAAS__ADMIN__USER_ID`
  - `AIMOS__SAAS__ADMIN__EMAIL`
  - `AIMOS__SAAS__ADMIN__PHONE`
  - `AIMOS__SAAS__ADMIN__PASSWORD`
- The plaintext password is hashed with bcrypt on first run and is never logged
  or returned.
- If the admin password is changed in config, it is re-hashed on the next boot.

#### Email OTP login flow
1. `POST /auth/login` with `{email, password}`.
2. Server verifies the password and sends a one-time login code to the admin
   email via SMTP.
3. When SMTP is not configured, the code is written to `state/maildrop/` so the
   operator can read it locally.
4. `POST /auth/login/verify` with `{email, code}` returns access/refresh tokens.
5. Access tokens are short-lived (default 15 minutes); refresh tokens rotate on
   use and are stored hashed in the auth DB.

#### Session management
- JWT access token with `sub` (user id) and `org` (organization id) claims.
- Secure cookie + `Authorization: Bearer` header support.
- `POST /auth/refresh` rotates refresh tokens.
- `POST /auth/logout` revokes the refresh token.

### 3.2 Settings store

- `SettingsStore(user_id="default")` lives in `state/auth.sqlite` (same DB as
  auth; can be Postgres via `AIMOS__SAAS__DATABASE_URL`).
- Two JSON columns:
  - `config` — runtime overrides (mode, features, mandate, paper, training).
  - `secrets` — encrypted exchange API credentials.
- Exchange secrets are encrypted at rest with a Fernet key stored in
  `state/.settings_key` (mode `0600`).
- `/api/v2/settings` returns the merged effective config and exchange **metadata**
  only (no plaintext keys).
- `/api/v2/settings/exchange` accepts `apiKey` and `secret`, stores them
  encrypted, and returns metadata.
- `runtime/serve.py` reads decrypted credentials through
  `SettingsStore.get_exchange_credentials()` for live broker construction.

### 3.3 Runtime integration

- `aimos/saas/config_tenant.py` merges `SettingsStore("default").get_config()` on
  top of `load_params()` when SaaS is enabled.
- `runtime/serve.py` uses `load_params_for_org` so paper/live mode, features,
  mandate limits, and training parameters can be changed through the UI without
  editing YAML files.
- Exchange credentials are taken from `SettingsStore` instead of a secrets YAML
  file; the live path still requires `multi_venue_live`, `mode=live` or
  `mandate.enabled`, a complete go-live ladder, and ≥2 venues with keys.

### 3.4 Dashboard

- Login screen is two-step: email + password, then OTP code.
- `Settings.jsx` is a single-user control panel with sections for:
  - Mode (paper / testnet / live) and feature toggles.
  - Mandate (enable + limits).
  - Paper config (equity, max symbols, cross venues).
  - Exchange API keys (add/remove, encrypted at rest).
  - Training parameters (symbols, timeframe, months).
  - Effective config preview.
- When `features.saas_enabled` is `false`, the dashboard falls back to the
  original local single-user experience (no login).

---

## 4. Data Model

SQLAlchemy 2.0 models in `aimos/saas/models.py`. Multi-tenant tables remain for
backward compatibility but the UI/runtime no longer use them.

```text
User
  id, email, email_verified, phone_number, phone_verified, password_hash, created_at

Organization
  id, name, slug, owner_id, created_at, mode

OrganizationMember
  user_id, organization_id, role, joined_at

RefreshToken
  id, user_id, token_hash, expires_at, revoked_at

EmailLoginCode
  id, user_id, code_hash, expires_at, used

user_settings  (SettingsStore ORM model)
  user_id, config, secrets
```

---

## 5. Dependencies

```toml
[project.optional-dependencies]
saas = [
  "bcrypt==4.3.0",
  "PyJWT==2.10.1",
  "cryptography==44.0.1",
  "email-validator==2.2.0",
]
```

- `bcrypt` — password hashing.
- `PyJWT` — JWT access/refresh tokens.
- `cryptography` — Fernet encryption for settings store and OTP hashing.
- `email-validator` — pydantic email validation.

---

## 6. API Surface

### Auth
- `POST /auth/login` — verify admin password; email a login OTP.
- `POST /auth/login/verify` — verify OTP; return tokens.
- `POST /auth/refresh` — rotate refresh token.
- `POST /auth/logout` — revoke refresh token.
- `GET /api/v2/status` — public probe returning `{"saas_enabled": bool}`.

### Settings (requires JWT)
- `GET /api/v2/me` — current admin user.
- `GET /api/v2/settings` — effective config + exchange metadata.
- `PATCH /api/v2/settings/config` — update config overrides.
- `POST /api/v2/settings/exchange` — add encrypted exchange credentials.
- `DELETE /api/v2/settings/exchange/{venue}` — remove exchange credentials.

### Trading endpoints
- Existing `/api/*` endpoints require `Authorization: Bearer <token>` and
  `X-Organization-Id: <org-id>` when SaaS is enabled; `api.js` sends these
  automatically after login. The org id comes from the token response and is
  the seeded admin's default organization.

---

## 7. Configuration

Example `config/saas.yaml`:

```yaml
enabled: true
database_url: ""                          # defaults to sqlite:///state/auth.sqlite
jwt_secret: ""                          # auto-generated if empty
access_token_expire_minutes: 15
refresh_token_expire_days: 30
otp_expire_minutes: 10

admin:
  user_id: "admin"
  email: "admin@example.com"
  phone: "+1234567890"
  password: "A-strong-password-123!"      # hashed on first run

smtp:
  host: "smtp.example.com"
  port: 587
  username: "..."
  password: "..."
  use_tls: true
  from_address: "noreply@example.com"
```

All values are overridable with `AIMOS__SAAS__*` environment variables.

---

## 8. Task Tracker

Legend: `[x]` completed · `[ ]` pending

### Auth & admin
- [x] Single admin user seeded from `config/saas.yaml` / env.
- [x] Email OTP login flow (`/auth/login`, `/auth/login/verify`).
- [x] Removed public registration, Google/Apple OAuth, phone OTP, and
  forgot-password endpoints.
- [x] JWT access/refresh tokens with rotation.
- [x] Dashboard two-step login screen.
- [x] Tests for admin login, OTP, refresh, logout.

### Settings store
- [x] `SettingsStore` with Fernet-encrypted exchange secrets.
- [x] `/api/v2/settings` endpoints for config and exchange keys.
- [x] `runtime/serve.py` loads effective params and exchange credentials from
  the store.
- [x] `Settings.jsx` single-user control panel.
- [x] Tests for settings store, config merge, and exchange-key redaction.

### Documentation
- [x] `CHANGELOG.md` updated.
- [x] `specs/OPERATIONS.md` updated.
- [x] `specs/STATUS.md` updated.
- [x] This spec rewritten to reflect the single-admin model.

### Verification
- [x] `python -m pytest` — green.
- [x] `python scripts/check_magic_numbers.py` — green.
- [x] `python scripts/check_no_naive_datetime.py` — green.
- [x] `lint-imports` — green.
- [x] `npm run build` — green.
- [x] `python -m aimos.runtime.paper_trader --offline --ticks 3` — green.
