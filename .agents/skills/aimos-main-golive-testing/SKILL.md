---
name: aimos-main-golive-testing
description: How to run the final go-live end-to-end verification on the AIMOS main branch, including the full operator workflow, auth, settings, controls, killswitch, backup, and SPA path-traversal checks.
---

# AIMOS `main` go-live end-to-end verification

## When to use

When asked to run the final go-live verification against the `main` branch of `Wasim-Shaikh25/aimos`:
- Full operator login (email + OTP) and session flow.
- Navigate every major dashboard screen and check for console errors.
- Add a fake exchange API key and verify encryption/redaction.
- Flip a runtime feature flag and confirm `/api/features` reflects it.
- Trigger the killswitch and verify `halted` state; note the missing reset UI/endpoint.
- Run `scripts/backup_journal.py` and confirm the verified snapshot.
- Confirm SPA path traversal returns the shell, not arbitrary files.

## Preconditions

- Python 3.11.11 via pyenv and the repo extras (`dev,data,serve,saas,ml,runtime`) installed.
- Dashboard built: `(cd dashboard && npm install && npm run build)`.
- No other process on port 8000.
- Seed the auth DB with `Organization.id="local"` and `User.email="admin@example.com"`:
  ```bash
  cd /home/ubuntu/repos/aimos
  AIMOS__SAAS__DATABASE_URL=sqlite:///state/auth_test.sqlite alembic upgrade head
  python /home/ubuntu/seed_main_auth.py   # inserts admin/local without Base.metadata.create_all
  ```
- Set `AIMOS_RUNTIME_ORG_ID=local` so the access-token `org` claim, the dashboard `X-Organization-Id` header, and the runtime org all match.

## Start the server

```bash
cd /home/ubuntu/repos/aimos
AIMOS__SAAS__ENABLED=true \
AIMOS__SAAS__ADMIN__EMAIL=admin@example.com \
AIMOS__SAAS__ADMIN__PASSWORD=AdminPass123! \
AIMOS__SAAS__JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx \
AIMOS__SAAS__DATABASE_URL=sqlite:///state/auth_main.sqlite \
AIMOS_DEV_MAILDROP=1 \
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS_RUNTIME_ORG_ID=local \
  python -m aimos.runtime.serve
```

## Login / session

The React-controlled email/password/OTP inputs do not reliably register values typed by the low-level `computer` `type` tool (same issue as the PR #6 auth flow). Drive the login via the browser console in an incognito window:

```javascript
fetch('/auth/login', {
  method: 'POST', headers: {'Content-Type':'application/json'},
  body: JSON.stringify({email:'admin@example.com', password:'AdminPass123!'})
}).then(r => r.json()).then(() => {
  const code = prompt('Paste OTP from state/maildrop/login-admin@example.com.txt');
  return fetch('/auth/login/verify', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email:'admin@example.com', code})
  }).then(r => r.json());
}).then(d => {
  localStorage.setItem('aimos_org', d.organization_id);
  location.reload();
});
```

Verify:
- `POST /auth/login/verify` returns `200` with `access_token` and `organization_id: "local"`.
- The response body does **not** contain `refresh_token`.
- `Set-Cookie` includes `refresh_token; HttpOnly; Path=/; SameSite=strict`.
- Security headers include `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- `localStorage.getItem('access_token')` is `null`; `localStorage.getItem('aimos_org')` is `"local"`.

## Dashboard screen navigation

With DevTools Console open (preserve log), click every side-nav route and confirm each renders its heading:

- `/` Markets
- `/positions` Positions & Risk (stress panel)
- `/performance` Performance (Equity curve + Alpha/Beta tiles)
- `/golive` Go-Live
- `/controls` Controls
- `/settings` Settings
- `/assistant` AI Analyst (disabled by default)
- `/engines` Observation Engines
- `/candles` Candlestick chart
- `/trades` Trade History
- `/balances` Balances
- `/monitor` Feature Monitor
- `/decisions` Decisions

Check DevTools Console for red JavaScript errors after the full navigation pass. Note: an initial `401` from `/auth/refresh` in an incognito window is expected before login.

## Encrypted exchange key

In the Settings UI, scroll to **Exchange API keys**. If the form inputs do not register automation typing, call the exact API the UI calls:

```bash
TOKEN=<access_token>
curl -s -X POST http://127.0.0.1:8000/api/v2/settings/exchange \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"venue":"binance","apiKey":"TEST_API_KEY_12345","secret":"TEST_SECRET_67890","testnet":true,"withdraw":false}'
```

Then reload `/settings` and verify:
- Configured exchanges becomes `1`.
- The exchange table shows `binance`, `Has key: yes`, `Testnet: yes`.
- `GET /api/v2/settings` returns only `has_key`/`has_secret` metadata and no `apiKey`/`secret`.
- The raw response string does not contain the literal fake key or secret.
- In the auth DB `user_settings` row (`user_id='default'`), `apiKey`/`secret` are Fernet-encrypted tokens (`gAAAAAB...`).

## Feature toggle

In **Controls**, the `Enable`/`Disable` buttons may not visually update after a single click in automation. Flip the toggle via the API and reload the page:

```bash
curl -s -X POST http://127.0.0.1:8000/api/control/feature \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"confirm":"CONFIRM","name":"cross_exchange","enabled":true}'

curl -s http://127.0.0.1:8000/api/features \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local"
```

Expected:
- `POST` returns `{"ok":true,"feature":"cross_exchange","enabled":true}`.
- `GET /api/features` returns `features.cross_exchange: true`.
- Reload `/controls` and the UI badge switches to `on`.
- `GET /api/v2/status` returns `saas_enabled`, `features`, and `halted`.

## Killswitch

The dashboard **Controls** screen now has a Killswitch panel. Trigger and reset via API:

```bash
curl -s -X POST http://127.0.0.1:8000/api/control/killswitch \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"confirm":"CONFIRM"}'
# {"ok":true,"halted":true}

curl -s -X POST http://127.0.0.1:8000/api/control/unhalt \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"confirm":"CONFIRM"}'
# {"ok":true,"halted":false}
```

Verify:
- `GET /api/features` and `GET /api/v2/status` show `"halted": true` after the killswitch.
- `Controls` screen shows **Halted** status and a **Reset halt** button.
- Reset clears the `RUNTIME_HALT` file (if it exists) and the dashboard toggles are re-enabled.

## Verified journal backup

```bash
python scripts/backup_journal.py --src state/aimos.sqlite --dest backups --keep 3
```

Expected:
- `backup OK: backups/journal-<timestamp>.sqlite (verified) -> backups/journal-latest.sqlite`
- `backups/journal-latest.sqlite` exists as a regular file and is queryable.

## SPA path traversal closed

```bash
curl -s http://127.0.0.1:8000/../state/.jwt_secret > /tmp/traverse1.html
curl -s 'http://127.0.0.1:8000/../%2e%2e/state/.settings_key' > /tmp/traverse2.html
```

Expected:
- Both return HTTP `200` and the SPA shell (`<!doctype html><html lang="en">...`).
- Neither contains the literal contents of `.jwt_secret` or `.settings_key`.

## Devin secrets needed

- None for the offline SaaS flow.
- Real exchange API keys are not required; use fake values.
