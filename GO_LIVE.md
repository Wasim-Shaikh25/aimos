# AIMOS — Go-Live Runbook (§23.8)

Real-money trading is **fail-closed**: it unlocks only when *every* gate below is
signed off. The **Go-Live** dashboard screen (and `GET /api/golive`) tracks
progress; time-based gates show auto progress but still need an explicit operator
sign-off — **nothing goes live on a timer, and no dashboard flag can flip live
trading** (those are locked on the Controls screen).

This is an operator process, not a feature to build. The code paths all exist and
are unit-tested; gate 3 (testnet) is where the live path is first proven against a
real exchange.

## The ladder

| # | Gate | How to clear it |
|---|------|-----------------|
| 1 | **Validated 12-month backtest** | Run the backtester on the recorded 12-mo dataset; confirm permutation p<0.05, bootstrap CI, benchmarks beaten (§9.3/§20.2). Sign off on the Go-Live screen. |
| 2 | **4 weeks paper** | Run `docker compose up -d` for ≥28 days; the screen auto-tracks paper days from the journal. Sign off when green. |
| 3 | **1 week testnet** | Get **testnet** keys (withdrawals off), set `AIMOS_SECRETS_FILE`, enable a small **testnet** mandate in `config/mandate.yaml`, then run `python -m scripts.testnet_order --exchange binance`. This places one tiny real order on testnet, cancels, reconciles, and starts the 7-day clock. Let it run a week, verify fills/reconcile, sign off. |
| 4 | **Security signoff + restore drill** | Confirm keys are withdrawal-disabled (§23.4), run a backup/restore drill (§23.5), review the incident runbook. Sign off. |
| 5 | **10% canary** | Set `mode: live`, mandate enabled with **10%** size caps, real (withdrawal-disabled) keys. Run 2 weeks; confirm paper-vs-live divergence stays within tolerance (the DivergenceTracker demotes a plugin that diverges). Sign off. |
| 6 | **Scale in 25% steps** | Raise the mandate caps in 25% steps, divergence-gated, to full size. Sign off. |

When all six are signed off, `live_allowed` is true and the go-live screen shows
**ALLOWED**. Live trading itself is still governed by `mandate.yaml` (fail-closed)
and the `mode: live` switch — both deliberate, both outside any dashboard button.

### Hard boot guard (belt-and-suspenders)

The app **refuses to start** in `mode: live` (or with the mandate enabled) until
every gate is signed off — `guard_live_boot` raises `LiveNotAllowedError` at
startup. So a misconfigured deploy physically cannot trade real money before the
ladder is complete. Paper mode is never affected.

## What "going live" requires that time alone does not

- **Funded accounts + withdrawal-disabled API keys** on each venue.
- **The testnet stage (gate 3)** — the live code is unit-tested against a *mock*;
  testnet is where it first meets a real exchange API.
- **`mandate.yaml`** configured with real limits and enabled.
- **Real data feeds** for streaming-dependent features (real scalp fast-loop,
  cross-venue streaming, on-chain, news LLM) — these need provider subscriptions.

## Emergency stop

- Dashboard: **Positions & Risk → killswitch** (CONFIRM-gated).
- Telegram: `/killswitch` (nonce-confirmed).
- File: create `RUNTIME_HALT` in the working dir — the loop halts, forces NO_TRADE.
