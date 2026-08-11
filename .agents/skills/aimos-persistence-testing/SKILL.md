---
name: AIMOS persistence backend smoke test
description: How to end-to-end test the AIMOS unified PostgreSQL/SQLite persistence backend, including restart survival of the journal and the runtime state stores.
---

# AIMOS persistence backend end-to-end testing

## Goal

Verify that setting `storage.database_url` (env `AIMOS__STORAGE__DATABASE_URL`) moves
the journal, runtime state, controls, and model registry onto one SQLAlchemy-backed
database, and that decisions survive a server restart.

## Environment

- Python 3.11.11 via pyenv and the editable package with extras `runtime`, `serve`,
  and `data`:
  ```bash
  export PATH="$HOME/.pyenv/bin:$PATH"
  eval "$(pyenv init -)"
  pyenv local 3.11.11
  python -m pip install -e '.[runtime,serve,data]'
  ```
- No exchange credentials or Telegram tokens are needed for offline synthetic data.

## Starting the server for a persistence smoke test

```bash
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__FEATURES__LIVE_DATA=false \
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=60 \
AIMOS__STORAGE__DATABASE_URL=sqlite:///tmp/aimos_e2e_test.db \
  python -m aimos.runtime.serve
```

## SQLite URL semantics

`sqlite:///tmp/aimos_e2e_test.db` is a relative path under the repo (`tmp/aimos_e2e_test.db`)
because SQLAlchemy treats three slashes after `sqlite://` as relative. To use the
absolute path `/tmp/aimos_e2e_test.db`, use four slashes:
`sqlite:////tmp/aimos_e2e_test.db`. Either URL exercises the same SQLAlchemy backend
path.

## Verification sequence

1. Confirm `/healthz`, `/readyz`, `/api/v2/status`, `/api/decisions?limit=2`,
   `/api/features`, `/api/models`, `/api/positions`, and `/api/balances` return 200.
2. Capture `/api/journal/stats` to record `n_decisions` before shutdown.
3. Capture a few `decision_id` values from `/api/decisions`.
4. Stop the server, then restart it with the same `AIMOS__STORAGE__DATABASE_URL`.
5. Re-check `/api/journal/stats` — `n_decisions` must not reset to 0.
6. Re-check `/api/decisions` and optionally `/api/decision/{id}/anatomy` for a
   pre-shutdown `decision_id`.

## Expected gotchas

- The first `/readyz` may return 503 until the paper loop writes its first heartbeat.
  With `loop_seconds=1` this usually happens within a few seconds.
- `/api/positions` is typically empty in the default synthetic run because no trades
  have fired yet; the expected response is `{"positions":[]}`.
- `/api/balances` returns simulated data when no exchange keys are configured.
- The dashboard `dist/` directory may not be built; the API still works and serves
  JSON endpoints, but `/` will not render the UI.
- Server logs will show `journal_backup_skipped_database` when the journal is DB-backed;
  this is expected.

## Devin Secrets Needed

None for offline synthetic mode. If you want to exercise Postgres, set
`AIMOS__STORAGE__DATABASE_URL=postgresql://user:pass@host/db` (or
`postgresql+psycopg://` if no driver suffix is configured); AIMOS normalizes
`postgresql://` to `postgresql+psycopg://` when `psycopg` is installed.
