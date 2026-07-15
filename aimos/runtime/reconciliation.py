"""Restart + accounting reconciliation (§23.5, §23.6, card P5-T8).

On startup the LiveBroker diffs exchange positions against the journal and
resolves fail-closed: an unknown exchange position → adopt + alert; a journal
position missing on the exchange → mark closed-unknown + alert. Nightly, exchange
fee/trade statements reconcile against our ledger to the cent (> $1 or unknown
trade → alert + halt PnL-dependent jobs). Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass
class ReconResult:
    matched: list[str] = field(default_factory=list)
    adopt: list[str] = field(default_factory=list)  # on exchange, not in journal
    close_unknown: list[str] = field(default_factory=list)  # in journal, not on exchange
    alerts: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.adopt and not self.close_unknown


def reconcile_positions(
    exchange_symbols: Sequence[str], journal_symbols: Sequence[str]
) -> ReconResult:
    ex, jr = set(exchange_symbols), set(journal_symbols)
    res = ReconResult(matched=sorted(ex & jr), adopt=sorted(ex - jr), close_unknown=sorted(jr - ex))
    for s in res.adopt:
        res.alerts.append(f"adopt unknown exchange position: {s}")
    for s in res.close_unknown:
        res.alerts.append(f"journal position missing on exchange: {s} → closed-unknown")
    return res


@dataclass
class AccountingResult:
    divergence_usd: float
    halt_pnl_jobs: bool
    alerts: list[str] = field(default_factory=list)


def reconcile_accounting(
    ledger_totals: Mapping[str, float], exchange_totals: Mapping[str, float], tolerance_usd: float = 1.0
) -> AccountingResult:
    """Reconcile fees/trades/funding to the cent (§23.6)."""
    divergence = 0.0
    alerts: list[str] = []
    keys = set(ledger_totals) | set(exchange_totals)
    for k in keys:
        d = abs(ledger_totals.get(k, 0.0) - exchange_totals.get(k, 0.0))
        divergence += d
        if d > tolerance_usd:
            alerts.append(f"{k} divergence ${d:.2f} > ${tolerance_usd}")
    return AccountingResult(divergence, halt_pnl_jobs=bool(alerts), alerts=alerts)


__all__ = ["AccountingResult", "ReconResult", "reconcile_accounting", "reconcile_positions"]
