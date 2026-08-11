---
name: AIMOS live-prereqs / connections end-to-end
description: |
  Test the Settings UI → encrypted exchange key store → `/api/connections/test`
  and `/api/connections` preflight flow.
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
   is fake) and the error payload never shows the raw `apiKey`/`secret` or a
   `signature=` parameter.
4. `POST /api/connections/test` with a bearer token should return only
   `{venue, configured, connected, can_trade, withdrawal_disabled, usdt_free, error}`
   and no `apiKey`/`secret`.
5. Stop and restart the server with the same `DATABASE_URL`.
6. `GET /api/connections` should now list `binance` with `configured: true` and
   `connected: false`; the `Connections` screen should show the same.
7. `GET /api/v2/settings` should return `has_key`/`has_secret` booleans only.

## Common gotchas

- `Settings.jsx` tabs did not respond to pointer/keyboard events in the test
  harness on the original branch; if needed, temporarily change `Tabs defaultValue`
  to `exchanges` for a screenshot, then revert.
