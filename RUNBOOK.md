# RUNBOOK.md — Operations (§23.7)

Operational procedures for AIMOS. Paper mode is the default everywhere; live
requires the §23.8 go-live ladder, `mandate.yaml`, and withdrawal-disabled keys.

## Start / stop / upgrade
- **Start:** `docker compose up -d` — trading runtime, dashboard, telegram bot,
  postgres, watchdog (research service is opt-in: `--profile research`).
- **Stop:** `docker compose down` (positions persist in the journal; restart
  reconciliation resolves state on next boot).
- **Upgrade:** pull, `docker compose build`, `docker compose up -d`. Vendored code
  is frozen — re-vendoring is a deliberate, human-approved event (§22.3).

## Controls
- **Pause (safe):** dashboard `Pause` (typed CONFIRM) or Telegram `/pause` —
  pipeline keeps observing + journaling, evaluator forced NO_TRADE (§15.2).
- **Kill switch:** create the `RUNTIME_HALT` file, or dashboard/Telegram
  `/killswitch` — flatten + halt (§7.4 rule 5).

## Incident playbooks
- **Exchange down:** data-quality gate marks the venue degraded and switches to
  the secondary feed (§23.3); open cross-venue positions on it flatten (§16.1C).
- **Depeg:** depeg guard suspends the quote + emits a 🚨 alert (§16.1B-3); arb
  math converts legs to USD via live stable rates.
- **Runaway losses:** daily stop (−2%) forces NO_TRADE until the next UTC day;
  protections (§21.1) lock symbols after repeated stops.
- **Corrupted DB:** restore from backup and verify — `scripts/restore_drill.sh`;
  never trade on inconsistent state (restart reconciliation is fail-closed).

## Reconciliation & accounting
- **On startup:** `reconcile_positions` diffs exchange vs journal → adopt unknown
  / mark closed-unknown, alert on any divergence.
- **Nightly:** `reconcile_accounting` reconciles fees/trades/funding to the cent;
  divergence > $1 alerts and halts PnL-dependent jobs (calibration/training).
- **Tax export:** `python -m aimos.learning.tax_export --tax-year 2026 --journal
  <db> --out fills.csv`.

## Backups
- Hourly local snapshot + daily encrypted off-site (rclone). **Monthly restore
  drill is mandatory** — a backup never restored is not a backup (§23.5).

## Go-live checklist (§23.8, in order — each journaled)
1. 12-month backtest passes §20.2 validation (permutation p<0.05, Sharpe CI>0).
2. ≥ 4 weeks paper trading; paper metrics within CI of backtest.
3. Exchange testnet 1 week (order lifecycle, partial fills, cancels, reconcile).
4. Security checklist §23.4 signed off; restore drill done.
5. Canary live: 10% capital, max 2 positions, 2 weeks.
6. Paper-vs-live divergence tracker runs forever; divergence > 2× modeled costs
   → plugin back to paper, cost model recalibrated.
7. Scale in 25% steps, one step per 2 green weeks.

## Weekly human routine
Review A1 proposals, check reconciliation, glance at the calibration curve.

## Build status
Phases 0–5 implemented (contracts → data → universe → observation →
intelligence → execution/journal/backtest → runtime/UI/telegram/ignition/risk
analytics). See `BUILD_TASKS.md`. Phase 6 (learning, agents, LLM sensor,
go-live) is the remaining work.
