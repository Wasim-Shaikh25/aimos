---
name: aimos-secrets-backup-testing
description: How to end-to-end test the AIMOS encrypted settings store, exchange API key redaction, SPA path-traversal hardening, and verified journal backup on the batch-7-secrets branch and later.
---

# Testing AIMOS secrets, settings, and verified backups

## When to use

When verifying changes to:
- `aimos/saas/settings_store.py` (Fernet-encrypted exchange keys)
- `aimos/saas/router.py` (`/api/v2/settings`, `/api/v2/settings/exchange`)
- `dashboard/src/screens/Settings.jsx` (exchange key UI)
- `aimos/runtime/serve.py` `_mount_dashboard` (SPA static-file hardening)
- `aimos/journal/backup.py` and `scripts/backup_journal.py`

## Preconditions

- Python 3.11.11 via pyenv and the repo extras (`dev,data,serve,saas,ml,runtime`) installed.
- Dashboard built: `(cd dashboard && npm install && npm run build)`.
- No other process on port 8000.
- **Run Alembic first** if you are seeding an auth DB manually. Do **not** use `Base.metadata.create_all` on the auth DB; that leaves Alembic thinking the schema is missing and it will fail on `alembic upgrade head` when the server starts.
  ```bash
  AIMOS__SAAS__DATABASE_URL=sqlite:///state/auth_test.sqlite alembic upgrade head
  ```
  Then seed with a script that only `INSERT`s rows (it must create `User`, `Organization` with `id="local"`, and `OrganizationMember`).
- Set `AIMOS_RUNTIME_ORG_ID=local` so the access-token `org` claim, the dashboard `X-Organization-Id` header, and the runtime org all match.

## Start the server

```bash
AIMOS__SAAS__ENABLED=true \
AIMOS__SAAS__ADMIN__EMAIL=admin@example.com \
AIMOS__SAAS__ADMIN__PASSWORD=AdminPass123! \
AIMOS__SAAS__JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx \
AIMOS__SAAS__DATABASE_URL=sqlite:///state/auth_test.sqlite \
AIMOS_DEV_MAILDROP=1 \
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS_RUNTIME_ORG_ID=local \
  python -m aimos.runtime.serve
```

## Browser verification

1. Open Chrome to `http://127.0.0.1:8000/`, maximize, and open DevTools Console (preserve log).
2. Log in with `admin@example.com` / `AdminPass123!`, read the OTP from `state/maildrop/login-admin@example.com.txt`, and enter it.
3. Navigate to **Settings**.
4. Scroll to **Exchange API keys** and add a fake key (e.g., venue `kraken`, API key `FAKE_KEY_12345`, secret `FAKE_SECRET_67890`).
5. Wait for `Added kraken key` and the table to show `Has key: yes`.

## Notes on test automation

- The React-controlled inputs in `Settings.jsx` and `auth.jsx` may not accept values typed by the low-level `computer` `type` tool. If the form does not submit, drive the same endpoint with `curl` or the browser console:
  ```javascript
  fetch('/auth/login/verify', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@example.com', code: '<OTP>' })
  }).then(r => r.json()).then(d => {
    localStorage.setItem('aimos_org', d.organization_id);
    location.reload();
  });
  ```
  Then reload the page and verify the UI state.

## API / shell verification

### Encrypted/redacted exchange keys

```bash
TOKEN=<access_token>
curl -s -X POST http://127.0.0.1:8000/api/v2/settings/exchange \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local" \
  -H "Content-Type: application/json" \
  -d '{"venue":"kraken","apiKey":"FAKE_KEY","secret":"FAKE_SECRET","testnet":true,"withdraw":false}'

curl -s http://127.0.0.1:8000/api/v2/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: local"
```

Expected:
- `POST` returns `200` with metadata only (`has_key`, `has_secret`, `testnet`, `withdraw`); no `apiKey` or `secret`.
- `GET /api/v2/settings` `exchanges.kraken` has `has_key: true` and `has_secret: true` and does **not** contain `apiKey`/`secret`.
- The `user_settings` row in the auth SQLite DB stores Fernet tokens (`gAAAAAB...`) for `apiKey` and `secret`.

### SPA path traversal closed

```bash
curl -s http://127.0.0.1:8000/../state/.jwt_secret
curl -s 'http://127.0.0.1:8000/../%2e%2e/state/.settings_key'
```

Expected:
- Both return `200` and the SPA shell (starts with `<!doctype html>`).
- Neither returns the contents of `state/.jwt_secret` or `state/.settings_key`.

### Verified journal backup

```bash
python scripts/backup_journal.py --src state/aimos.sqlite --dest backups --keep 3
```

Expected:
- Exits `0` and prints `backup OK: backups/journal-<timestamp>.sqlite (verified) -> backups/journal-latest.sqlite`.
- `backups/journal-latest.sqlite` exists as a regular file and is queryable.

## Devin secrets needed

- None for the offline SaaS flow.
- Real exchange API keys are not required for testing; use fake values.
