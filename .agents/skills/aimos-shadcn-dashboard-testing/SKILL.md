---
name: aimos-shadcn-dashboard-testing
description: How to end-to-end test the AIMOS shadcn/ui dashboard — build, single-user login, Settings tabs, redacted exchange keys, Config/Models/Controls/Go-Live screens, navigation, restart persistence, and Python gates.
---

# AIMOS shadcn/ui dashboard end-to-end testing

## Goal

Verify the shadcn/ui dashboard overhaul on branches that include the new card/input
components, Settings tabs, and structured forms/table views.

## Preconditions

- Python 3.11.11 active (`pyenv local 3.11.11`).
- AIMOS editable install with `[dev,runtime,serve,data]` extras.
- Node/Vite dashboard built: `(cd dashboard && npm install && npm run build)`.
- Clean SQLite test database (or remove stale `tmp/aimos_test.db*` files).

## Devin Secrets Needed

- `AIMOS_ADMIN_USERNAME` and `AIMOS_ADMIN_PASSWORD` are passed as env vars.
- `AIMOS_JWT_SECRET` (any 32+ byte string works for local testing).

## Serve command

```bash
cd /home/ubuntu/repos/aimos
rm -f tmp/aimos_test.db*
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS__STORAGE__DATABASE_URL=sqlite:///tmp/aimos_test.db \
AIMOS_ADMIN_USERNAME=admin \
AIMOS_ADMIN_PASSWORD=AdminPass123! \
AIMOS_JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx \
  /home/ubuntu/.pyenv/versions/3.11.11/bin/python -m aimos.runtime.serve
```

## Browser flow

1. Open `http://127.0.0.1:8000/` in a maximized incognito Chrome window.
2. **Login** — expect a shadcn `Card` titled `AIMOS` with username/password
   `Input` fields and a `Sign in` button. Use keyboard submission (focus password
   and press Enter) if pointer clicks on the shadcn `Button` are not reliably
   registered by the test harness.
3. **Settings** — navigate `/settings`. Verify tabs:
   - Mode & Features (Select for mode, Switch toggles)
   - Mandate (Switch + numeric Inputs)
   - Paper (numeric Inputs + data venue text input)
   - Exchanges (add-key form with redacted saved-keys `Table`)
   - Training (Symbols, Timeframe Select defaulting to `1h`, Months defaulting to
     `12`)
   - Effective config (Card grid of config sections, no `<pre>` JSON)
4. **Add a fake exchange key** — in Exchanges, set Venue `binance`, a fake API key
   and secret, Testnet on, and submit. Refresh and confirm the `Table` shows only
   `Has key` and `Testnet` badges (`yes`/`yes`), not the raw key/secret values.
5. **Config, Models, Controls, Go-Live** — visit `/config`, `/models`, `/controls`,
   `/golive`. All should use `Card`/`Table`/`Badge`/`Switch` components, with muted
   helper text in grey (`text-muted-foreground`). Off/no/disabled state badges
   should render in the neutral `secondary`/`flat` grey, not red.
6. **Navigation** — spot-check all top-level nav routes from `dashboard/src/App.jsx`.
   Each should render its screen without a full-page red error overlay.
7. **Restart survival** — stop the backend with SIGTERM, restart with the same
   `AIMOS__STORAGE__DATABASE_URL`, and refresh the dashboard. It should reload
   authenticated (httpOnly `refresh_token` cookie) and keep saved settings/exchange
   metadata. The `Decisions` count in the top chrome should continue from the
   pre-shutdown value.

## Python gates

Run from repo root with pyenv bin first in `PATH` so `lint-imports` and the
restore-drill `python` invocation resolve correctly:

```bash
export PATH="/home/ubuntu/.pyenv/versions/3.11.11/bin:$PATH"
python -m pytest -q
python scripts/check_magic_numbers.py
python scripts/check_no_naive_datetime.py
lint-imports
```

## Common gotchas

- **Stale `__pycache__`:** After switching from SaaS/single-user branches, stale
  `.pyc` files can make pytest import removed `aimos.saas` modules and fail with
  missing `config/saas.yaml`. Remove all `__pycache__` directories before running
  `pytest`.
- **Auth rate limiter:** The auth endpoints are rate-limited to 10 requests per 60 s
  per IP. Rapid full-page reloads (each triggers `/auth/refresh`) will return 429
  and drop the session. Pace page loads or use client-side nav clicks; restart the
  server if the limiter trips.
- **`lint-imports` not found:** It is installed under the pyenv 3.11.11 bin
  directory; add it to `PATH` before `pytest` so `tests/test_lints.py` can invoke it.
- **`sqlite:///tmp/aimos_test.db` resolves to `tmp/aimos_test.db` relative to the
  repo root, not the absolute `/tmp` directory. Use this consistently across
  starts.
