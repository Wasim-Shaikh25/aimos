---
name: AIMOS live-prereqs / connections end-to-end
description: |
  Test the Settings UI → encrypted exchange key store → `/api/connections/test`
  and `/api/connections` preflight flow on the live-prereqs branch.
---

## Goal

Verify that exchange API keys saved in `Settings > Exchanges` are persisted in
`SettingsStore`, read by `_run_preflight` at boot, tested on demand by
`POST /api/connections/test`, and displayed redacted in the UI without exposing
credentials.

## Preconditions

- Use the same single-user + SQLite serve command as `aimos-shadcn-dashboard-testing`.
- `npm run build` in `dashboard/` succeeds.
- A clean `sqlite:///tmp/aimos_test.db` (relative to repo root) is used consistently.

## Test sequence

1. Log in, open `Settings > Exchanges`.
2. Add a fake `binance` testnet key/secret, save.
3. Click `Test` and confirm the `Connection` badge changes to `failed` (the key
   is fake) but never shows the raw `apiKey`/`secret`.
4. `POST /api/connections/test` with a bearer token should return only
   `{venue, configured, connected, can_trade, withdrawal_disabled, usdt_free, error}`
   and no `apiKey`/`secret`.
5. Stop and restart the server with the same `DATABASE_URL`.
6. `GET /api/connections` should now list `binance` with `configured: true` and
   `connected: false`; the `Connections` screen should show the same.
7. `GET /api/v2/settings` should return `has_key`/`has_secret` booleans only.

## Common gotchas

- `serve.py` currently initializes `holder["connections"] = {}` instead of the
  preflight result. This makes `/api/connections` always return an empty list
  until the `connections` value is wired to `_run_preflight`'s output.
- `POST /api/connections/test` returns the raw ccxt error, which for Binance can
  include the signed request URL (`signature=...`). This leaks a derivative of
  the secret and should be sanitized before being returned to the UI.
- `scripts/validate_integration.py` imports `load_params_for_user` from
  `aimos.core.config`; it lives in `aimos.settings.config`.
- The branch may arrive with unresolved merge conflicts in `aimos/runtime/serve.py`,
  `scripts/validate_integration.py`, and `CHANGELOG.md`. Resolve those before
  runtime testing.
- `Settings.jsx` tabs did not respond to pointer/keyboard events in the test
  harness on this branch; if needed, temporarily change `Tabs defaultValue` to
  `exchanges` for a screenshot, then revert.
