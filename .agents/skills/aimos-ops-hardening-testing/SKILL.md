---
name: AIMOS security/ops hardening testing
description: How to verify the batch-2 health endpoints, decisions limit, go-live ladder, auth timing mask, and GPL tripwire end-to-end.
---

# AIMOS security/ops hardening testing (batch-2)

## Goal
Run offline end-to-end checks for the PR #4 batch: `/healthz`, `/readyz`, `/api/decisions?limit=`, the go-live ladder, `/auth/login` not-found timing, and `scripts/check_gpl_tripwire.py`.

## Environment
- Use Python 3.11 (pyenv local 3.11.11). The shell must set pyenv every time because it is not always on `PATH` by default:
  ```bash
  cd /home/ubuntu/repos/aimos
  export PATH="$HOME/.pyenv/bin:$PATH"
  eval "$(pyenv init -)"
  pyenv local 3.11.11
  ```
- Install runtime + serve extras:
  ```bash
  python -m pip install -e '.[runtime,serve]' --quiet
  ```
- Set offline flags:
  ```bash
  AIMOS__PAPER__USE_UNIVERSE=false
  AIMOS__FEATURES__LIVE_DATA=false
  ```

## Devin Secrets Needed
None for offline mode.
For the auth test set placeholders via env:
```bash
AIMOS_ADMIN_USERNAME=admin
AIMOS_ADMIN_PASSWORD=AdminPass123!
AIMOS_JWT_SECRET=test-secret-32-bytes-long-xxxxxxxxxx
```

## Key gotchas
- `TestClient` does not run the background paper loop, so `/readyz` stays 503 until you simulate a heartbeat by writing a fresh ISO timestamp to `state/heartbeat` (or by running the live `python -m aimos.runtime.serve` server and curling the endpoint before the first tick).
- `/api/control/*` endpoints require a loopback client in single-user mode. Use a real `curl` from `127.0.0.1` instead of `TestClient` for those checks if you hit a 401.
- Dashboard clicks may not register through the scaled coordinate space; `document.querySelector` and `button.click()` in the browser console can drive the UI as a fallback, and the state changes are still visible on the recording.
- `scripts/check_gpl_tripwire.py` runs under Python 3.11; the system `/usr/bin/python` (3.10) may fail on `import tomllib`.

## Verifying health endpoints
```python
from fastapi.testclient import TestClient
from aimos.runtime.serve import build_app

app = build_app(offline=True)
client = TestClient(app)
client.get("/healthz")  # -> 200 {"status":"ok"}
client.get("/readyz")  # -> 503 with heartbeat_age_seconds=null when no heartbeat
# Simulate a fresh loop tick by updating state/heartbeat
Path("state/heartbeat").write_text(datetime.now(timezone.utc).isoformat())
client.get("/readyz")  # -> 200 {"ready": true, "journal_writable": true, ...}
```

## Verifying decisions limit and go-live
Use `TestClient` with `build_app(offline=True)`:
- `GET /api/decisions?limit=50` -> 200
- `GET /api/decisions?limit=0`, `?limit=501`, `?limit=-1` -> 422
- `POST /api/control/golive` with `confirm: CONFIRM` and `gate: scaling` first -> 400 out-of-order
- Mark gates in order from `backtest_validated` to `scaling` -> each 200
- After all gates, `GET /api/golive` shows `live_allowed: true`, `percent: 100.0`
- `POST /api/control/golive` with `gate: testnet_1wk`, `passed: false` -> only `backtest_validated` and `paper_4wk` remain passed

## Verifying auth not-found timing mask
```python
client.post("/auth/login", json={"username":"nobody","password":"AdminPass123!"})
# -> 401 {"detail":"invalid credentials"}
client.post("/auth/login", json={"username":"admin","password":"WrongPass123!"})
# -> identical 401 message; no username-existence leak
```

## Verifying the GPL tripwire
```bash
python scripts/check_gpl_tripwire.py
```
It should exit 0. It prints any GPL-origin source files tracked in `vendor/GPL_TRIPWIRE.md` and any copyleft dependency pins in `pyproject.toml`.
