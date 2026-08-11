---
name: AIMOS risk-analytics dashboard testing
description: How to stand up the AIMOS backend and verify the risk-analytics endpoints and dashboard tiles end-to-end.
---

# AIMOS risk-analytics dashboard testing

## Goal
Run the AIMOS `serve` stack locally against synthetic/offline data and confirm that `/api/risk` returns a full VaR/ES + alpha/beta + factor-decomposition report, and that the dashboard Positions & Risk / Performance screens render the new tiles.

## Environment
- Use Python 3.11 (pyenv local 3.11.11).
- Ensure runtime extras are installed so APScheduler is available:
  ```bash
  cd /home/ubuntu/repos/aimos
  export PATH="$HOME/.pyenv/bin:$PATH"
  eval "$(pyenv init -)"
  pyenv local 3.11.11
  python -m pip install -e '.[runtime]' --quiet
  ```
- Build the dashboard whenever the source changes:
  ```bash
  (cd dashboard && npm install && npm run build)
  ```
- No API keys are needed for offline mode. Set `AIMOS__FEATURES__LIVE_DATA=false` to avoid public exchange calls.

## Devin Secrets Needed
None for offline paper mode. If you want live public data, `AIMOS__FEATURES__LIVE_DATA=true` and `pip install -e '.[data]'`, but no exchange API keys are used.

## Starting the stack
```bash
cd /home/ubuntu/repos/aimos
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"
pyenv local 3.11.11
AIMOS__PAPER__LOOP_SECONDS=1 \
AIMOS__PAPER__USE_UNIVERSE=false \
AIMOS__RISK__INTERVAL_SECONDS=1 \
AIMOS__RISK__MIN_SAMPLES=3 \
AIMOS__FEATURES__LIVE_DATA=false \
  python -m aimos.runtime.serve
```
- The server listens on `http://127.0.0.1:8000`.
- Wait until Uvicorn logs `Application startup complete.` and APScheduler logs `risk_analytics_scheduler_started`.
- The risk job will log `risk_analytics_updated sample_size=N` once enough equity-return samples accumulate (here `min_samples=3`, but it needs at least one paper-loop tick, so allow 5–10 s).

## Verifying the API
```bash
curl -s http://localhost:8000/api/risk | python -m json.tool
```
Required keys: `var_95_pct`, `es_95_pct`, `var_99_pct`, `es_99_pct`, `sample_size`, `computed_at`, plus nested `btc`, `basket`, and `factor` objects as described in `aimos/risk/analytics_runner.py`.

## Verifying the dashboard
- Open `http://localhost:8000/` in Chrome (or the system browser).
- The app runs in single-user mode: log in with `AIMOS_ADMIN_USERNAME`/`AIMOS_ADMIN_PASSWORD`.
- Navigate to **Positions & Risk** and confirm the **Stress panel (§24.1)** tiles:
  - VaR 95%, ES 95%, VaR 99%, ES 99%
  - BTC beta, BTC beta %, Idiosyncratic %
  - Alpha (annualized), Beta, t-stat table columns for BTC benchmark and T1 basket
- Navigate to **Performance** and confirm the **Alpha & Beta** section tiles:
  - BTC alpha, BTC beta
  - T1 basket alpha, T1 basket beta
  - BTC-beta factor %, Idiosyncratic %

## Common gotchas
- `EquityChart.jsx` historically used `chart.addLineSeries()`, which was removed in `lightweight-charts@5.x`. If the Performance screen is blank, check the browser console for `addLineSeries is not a function` and patch to `chart.addSeries(LineSeries, { ... })`.
- If the risk job is not running, verify `apscheduler` is installed (`python -c "import apscheduler"`); the backend silently skips the scheduler when the package is absent.
- If `/api/risk` returns only `{"note": "insufficient equity history ..."}`, the paper loop has not yet produced enough ticks; wait a few seconds and retry.
