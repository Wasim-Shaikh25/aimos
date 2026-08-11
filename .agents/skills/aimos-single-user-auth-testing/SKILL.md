---
name: aimos-single-user-auth-testing
description: How to end-to-end test the AIMOS single-user / no-SaaS auth flow, dashboard Settings UI, encrypted exchange key store, and unified persistence on the PR #17 branch and later.
---

# AIMOS single-user / no-SaaS end-to-end testing

## Goal

Verify that the single-user refactor (env credential auth, JWT access token + httpOnly
refresh cookie, `/api/v2/settings/*` endpoints, encrypted exchange key store, and
dashboard `Settings.jsx`) works end-to-end with the unified SQLite/PostgreSQL
persistence backend.

## Environment

- Python 3.11.11 via pyenv and the editable package with extras `runtime`, `serve`,
  and `data`.
- No exchange credentials or Telegram tokens are needed for offline synthetic data.
- Build the dashboard first:
  ```bash
  (cd dashboard && npm install && npm run build)
  ```

## Required environment variables

```bash
AIMOS_ADMIN_USERNAME=admin
AIMOS_ADMIN_PASSWORD=<a strong password>
AIMOS_JWT_SECRET=<at least 32 bytes, e.g. a long random string>
```

## Starting the server for single-user testing

```bash
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS__STORAGE__DATABASE_URL=sqlite:///tmp/aimos_e2e_test.db \
AIMOS_ADMIN_USERNAME=admin \
AIMOS_ADMIN_PASSWORD=AdminPass123! \
AIMOS_JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx \
  python -m aimos.runtime.serve
```

## SQLite URL semantics

`sqlite:///tmp/aimos_e2e_test.db` resolves to `tmp/aimos_e2e_test.db` relative to the
repo root (SQLAlchemy treats three slashes after `sqlite://` as a relative path).
Use `sqlite:////tmp/aimos_e2e_test.db` for the absolute path `/tmp/aimos_e2e_test.db`.
Either URL exercises the same SQLAlchemy backend path.

## Verification sequence

1. Open `http://127.0.0.1:8000/` in a browser.
2. Confirm the single-user login screen (username / password) appears.
3. Reject wrong credentials and confirm an inline error.
4. Log in with `admin` / `AIMOS_ADMIN_PASSWORD`.
5. Navigate to `/settings`.
6. Verify sections: Mode & features, Mandate, Paper config, Exchange API keys,
   Training data, and Effective config preview.
7. Save a fake testnet exchange key (e.g. `binance`) and confirm the UI table shows
   `Has key: yes`, `Testnet: yes`, and does **not** display the raw key or secret.
8. Use `curl` to confirm `/api/v2/settings` with a valid bearer token returns 200 and
   the JSON exchange metadata contains `has_key`/`has_secret` booleans but no
   `apiKey` or `secret` values.
9. Confirm `/api/v2/settings` without a token returns **401**. If it returns 500, the
   `AuthError` exception raised by `get_current_user` is not being converted to an
   HTTP 401 response; check `aimos/api/server.py` / `aimos/auth/router.py` for a
   missing `AuthError` exception handler.
10. Stop the server, restart it with the same `AIMOS__STORAGE__DATABASE_URL`, and
    confirm the dashboard reloads without re-asking for credentials (via the
    `refresh_token` cookie) and that previous settings + decisions survive.

## Known gotchas

- The dashboard `dist/` directory must be built; otherwise `serve.py` logs
  `dashboard_not_built` and `/` returns a plain message instead of the SPA.
- The first `/readyz` may return 503 until the paper loop writes its first heartbeat.
- `/api/v2/*` routes are treated as public by the auth middleware; protection is
  enforced inside each endpoint through `Depends(get_current_user)`. If an
  unauthenticated call returns 500, `AuthError` is not handled.
- `/api/positions` is typically empty in the default synthetic run; `/api/balances`
  returns simulated data.

## Devin Secrets Needed

None for offline synthetic mode. For Postgres persistence, set
`AIMOS__STORAGE__DATABASE_URL=postgresql://user:pass@host/db` (or
`postgresql+psycopg://`).
