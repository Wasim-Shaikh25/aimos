---
name: aimos-saas-auth-testing
description: How to end-to-end test the AIMOS SaaS auth flow (httpOnly refresh cookie, CSP headers, silent refresh, logout) and the AI analyst debate endpoint.
---

# Testing AIMOS SaaS auth + AI analyst (PR #6 style)

## When to use

When verifying changes to `aimos/saas/router.py`, `aimos/api/server.py` security headers, `aimos/runtime/assistant.py`, or the dashboard `auth.jsx`/`api.js`.

## Preconditions

- Python 3.11.11 via pyenv and the repo extras (`dev,data,serve,saas,ml,runtime`) installed.
- Dashboard built: `(cd dashboard && npm install && npm run build)`.
- Pre-seed a deterministic auth DB with `Organization.id = "local"` and `User.email = "admin@example.com"`, so `AIMOS_RUNTIME_ORG_ID=local`, the access-token `org` claim, and the dashboard `X-Organization-Id` header all match.
  - Example seed script pattern: create `User(id="admin", email="admin@example.com", email_verified=True)`, `Organization(id="local", name="Personal", owner_id="admin")`, `OrganizationMember(user_id="admin", organization_id="local", role="owner")`.

## Start the server

```bash
AIMOS__SAAS__ENABLED=true \
AIMOS__SAAS__ADMIN__EMAIL=admin@example.com \
AIMOS__SAAS__ADMIN__PASSWORD=AdminPass123! \
AIMOS__SAAS__JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx \
AIMOS__SAAS__DATABASE_URL=sqlite:///state/auth_pr6.sqlite \
AIMOS_DEV_MAILDROP=1 \
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS_RUNTIME_ORG_ID=local \
  python -m aimos.runtime.serve
```

## Browser verification

1. Open Chrome to `http://127.0.0.1:8000/golive`, maximize, and open DevTools Network (preserve log on).
2. Confirm the initial SPA response carries `Content-Security-Policy`, `X-Frame-Options: DENY`, and `X-Content-Type-Options: nosniff`.
3. Login with `admin@example.com` / `AdminPass123!`, read the OTP from `state/maildrop/login-admin@example.com.txt`, and enter it.
4. In DevTools Network inspect `POST /auth/login/verify`:
   - status 200
   - response body contains `access_token`, `user_id`, `organization_id`
   - `Set-Cookie` contains `refresh_token`, `HttpOnly`, `SameSite=strict`
5. In the DevTools Console run:
   - `localStorage.getItem('access_token')` → should be `null`
   - `localStorage.getItem('aimos_org')` → should be `"local"`
6. Reload the page; the dashboard should restore silently via `POST /auth/refresh` (200, new `Set-Cookie`, new `access_token`).
7. Click Logout; confirm `/auth/logout` clears the cookie and the page returns to the login screen.
8. Check that protected API responses still carry CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.

## Verification via curl

`Set-Cookie` attributes are easier to read with curl than from the DevTools detail pane:

```bash
# obtain a new OTP
curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"AdminPass123!"}'
CODE=$(cat state/maildrop/login-admin@example.com.txt)

# verify and capture Set-Cookie
curl -i -s -X POST http://127.0.0.1:8000/auth/login/verify \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@example.com\",\"code\":\"$CODE\"}"

# refresh
curl -i -s -X POST http://127.0.0.1:8000/auth/refresh \
  -H 'Cookie: refresh_token=<token>'

# logout
curl -i -s -X POST http://127.0.0.1:8000/auth/logout \
  -H 'Cookie: refresh_token=<token>'
```

Expected:
- `/auth/login/verify` → `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=2592000; Path=/; SameSite=strict`
- `/auth/refresh` → same `Set-Cookie` attributes plus a new `access_token` body
- `/auth/logout` → `Set-Cookie: refresh_token=""; Max-Age=0; Path=/` (note: current impl uses `SameSite=lax` on delete; watch for inconsistency)

## AI analyst debate endpoint

Run a `TestClient` script against `aimos.api.server.create_app` with a fake assistant:

- `GET /api/assistant/debate/{decision_id}` with `assistant=None` → `503` with message `assistant disabled (set assistant.enabled + ANTHROPIC_API_KEY)`.
- `GET /api/assistant/debate/{decision_id}` with a fake `Assistant.debate()` returning `{"decision_id": decision_id, "narrative": "Case for: ...\nCase against: ...", "grounded_on": {"decision_id": decision_id}}` → `200` JSON with `decision_id`, `narrative`, `grounded_on`; `narrative` must contain both substrings `Case for` and `Case against`.

For live UI testing without a real API key, navigate to `/assistant` and confirm:
- a disabled warning is shown instructing to enable `assistant.enabled` + `ANTHROPIC_API_KEY`.
- clicking a suggestion chip does not hang or expose internal errors; it should show a fallback unavailable message.

## Devin secrets needed

- None for the offline SaaS/auth flow.
- `ANTHROPIC_API_KEY` only if you want to test the live assistant/debate response instead of the 503 or a mock.

## Gotchas

- Each `/auth/login` or `/auth/login/verify` invalidates any prior refresh token for the user. Do not mix curl logins with an active browser session you intend to refresh.
- `document.querySelector('button').click()` in the DevTools console can hit the first `<button>` in the DOM, which may be Logout. Prefer explicit selectors for chat UI controls.
- The dashboard inputs are controlled React components; setting `.value` alone does not update state. Trigger `input`/`change` events or use the UI directly.
- `X-Organization-Id` must be `local` for all `/api/*` calls; seed the org ID to match `AIMOS_RUNTIME_ORG_ID`.
