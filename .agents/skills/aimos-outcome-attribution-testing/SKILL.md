---
name: AIMOS outcome attribution and go-live gate end-to-end testing
description: How to end-to-end test per-strategy outcome attribution on /api/performance and /api/strategies, and the run-card-gated /api/control/golive backtest_validated check.
---

# AIMOS outcome attribution + go-live gate E2E testing

## Goal
Verify that `aimos/journal/analytics.py` per-strategy attribution is surfaced by the
backend on `/api/performance` and `/api/strategies`, and that `GoLiveLadder.mark()`
requires a valid `specs/runcards/*.yaml` file with `validation.permutation_p < 0.05`
before the `backtest_validated` gate can be ticked.

## Environment

- Python 3.11.11 via pyenv, editable package installed with the `serve` extras:
  ```bash
  export PATH="$HOME/.pyenv/bin:$PATH"
  eval "$(pyenv init -)"
  pyenv local 3.11.11
  source .venv/bin/activate
  ```
- No exchange keys, no Telegram token, no LLM keys required; use paper/synthetic mode.

## Seeding a journal with known outcomes

The offline paper loop does not guarantee closed trades, so seed the SQLite journal
before starting the server:

```python
from datetime import datetime, timezone
from aimos.core.schemas import (
    Action, Behavior, DecisionRecord, Direction,
    MarketUnderstanding, OutcomeRecord, Regime, TradePlan,
)
from aimos.journal.journal import Journal

TS = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
j = Journal("/tmp/aimos_e2e_test.db")

mu = MarketUnderstanding(
    symbol="BTC/USDT", timestamp=TS, regime=Regime.TRENDING_UP,
    behavior=Behavior.CONTINUATION, direction_bias=Direction.BULLISH,
    p_up=0.7, horizon_minutes=240, confidence=0.6,
    coin_health=80, opportunity_score=70, risk_score=30,
)
plan = TradePlan(plugin="Breakout", symbol="BTC/USDT", action=Action.LONG,
                 entry=150.0, stop_loss=145.0, take_profit=160.0, size_quote=1000.0)
j.write_decision(DecisionRecord(
    timestamp=TS, symbol="BTC/USDT", understanding=mu, candidates=[],
    chosen=plan, mode="backtest", decision_id="d-Breakout"))

# write >=1 outcome per decision
j.write_outcome(OutcomeRecord(
    decision_id="d-Breakout", exit_time=TS, exit_price=160.0,
    pnl_r=1.0, pnl_quote=10.0, max_adverse_r=-0.1,
    max_favorable_r=1.0, exit_reason="tp"))
```

## Starting the backend for the test

Use a temporary journal path and force exactly one NO_TRADE paper tick so the loop
writes a heartbeat and exits without adding trades:

```bash
rm -rf /tmp/aimos_e2e_test.db /tmp/tenant_local_state state

# seed first
python /tmp/seed_attribution.py

env AIMOS__PAPER__USE_UNIVERSE=false \
    AIMOS__PAPER__SYMBOLS='["BTC/USDT"]' \
    AIMOS__PAPER__MAX_TICKS=1 \
    AIMOS__PAPER__LOOP_SECONDS=0 \
    AIMOS__PAPER__JOURNAL_PATH=/tmp/aimos_e2e_test.db \
    AIMOS__FEATURES__LIVE_DATA=false \
    AIMOS__EXECUTION__MIN_TRADE_SCORE=1.0 \
    AIMOS__HEALTH__HEARTBEAT_STALE_SECONDS=600 \
    python -m aimos.runtime.serve &
```

## Endpoints to exercise

- `GET http://127.0.0.1:8000/api/performance` — assert `from_outcomes.per_strategy` contains
  the seeded strategies, `low_sample` is `true` when `n < 30`, and `outcomes_caveat` is present.
- `GET http://127.0.0.1:8000/api/strategies` — assert every strategy row has an `outcomes`
  block with at least `trades`, `win_rate`, `pnl_quote`, `pnl_r`, `expectancy_r`,
  `avg_mae_r`, `avg_mfe_r`, `low_sample`.
- `GET http://127.0.0.1:8000/api/golive` — initial state: `backtest_validated` pending,
  `live_allowed` false.
- `POST http://127.0.0.1:8000/api/control/golive` with body
  `{"confirm":"CONFIRM","gate":"backtest_validated","passed":true}` — should return
  `400` with detail `"no run card with permutation p < 0.05"` when no valid run card exists.
- Create `specs/runcards/e2e_test.yaml` with:
  ```yaml
  validation:
    permutation_p: 0.01
  ```
  then re-run the same POST — should return `200` `{"ok": true, "gate": "backtest_validated"}`.
- Re-`GET /api/golive` — `backtest_validated` now `passed`, `live_allowed` still `false`.

## Gotchas

- `/docs` (FastAPI Swagger UI) may render blank in the browser because the default
  CSP (`script-src 'self'`) blocks the external Swagger JS CDN. Use the direct JSON
  endpoints (`/api/performance`, `/api/strategies`, `/api/golive`) instead; they are
  protected but allowed from loopback (`127.0.0.1`) without a token.
- The `min_trade_score` env trick only works because the field is validated `0..1`;
  setting it to `1.0` forces the evaluator to select `RiskOff`/NO_TRADE so the seeded
  outcomes are not mixed with synthetic loop trades.
- Remove stale `state/` and `go_live.json` before a gate test; otherwise a previous
  run's sign-offs may hide the failure.

## Devin Secrets Needed

None for offline/synthetic mode. The `/api/control/*` endpoints accept loopback callers
without a JWT, so no `AIMOS_ADMIN_USERNAME`/`AIMOS_ADMIN_PASSWORD` is required from the
local box.
