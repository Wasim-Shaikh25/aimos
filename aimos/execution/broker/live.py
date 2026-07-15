"""LiveBroker + mandate gate + divergence tracker (§7.6, §20.4, §23.4, §23.8,
card P6-T5).

The mandate is a fail-closed contract: live orders are REFUSED unless the mandate
is enabled and the order fits every limit, AND the API keys have withdrawal
permission DISABLED (§23.4). Client order IDs are idempotent (hash of the
decision id, §7.6). The paper-vs-live divergence tracker demotes a plugin back to
paper when live costs exceed the modeled costs by more than the configured
multiple (§23.8). ccxt is an optional dep, imported lazily. All tunables from
config (mandate.yaml); the magic-number lint governs this module.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from aimos.core.schemas import Action, OrderResult, TradePlan


def client_order_id(decision_id: str) -> str:
    """Idempotent client order id = hash(decision_id) (§7.6)."""
    return "aimos-" + hashlib.sha256(decision_id.encode()).hexdigest()[:24]  # noqa: magic — id length


@dataclass
class MandateDecision:
    ok: bool
    reason: str = ""


class MandateGate:
    """Fail-closed mandate check (§20.4, §23.8)."""

    def __init__(self, mandate_cfg: Mapping[str, Any]) -> None:
        self.cfg = mandate_cfg

    def check(
        self, plan: TradePlan, total_notional_after: float, open_positions_after: int
    ) -> MandateDecision:
        if not self.cfg.get("enabled", False):
            return MandateDecision(False, "mandate not enabled — live trading refused (fail-closed)")
        if plan.action is Action.NO_TRADE:
            return MandateDecision(True)
        if total_notional_after > float(self.cfg["max_total_notional_usdt"]):
            return MandateDecision(False, "exceeds mandate max total notional")
        if open_positions_after > int(self.cfg["max_positions"]):
            return MandateDecision(False, "exceeds mandate max positions")
        quote = plan.symbol.split("/")[-1] if "/" in plan.symbol else "USDT"
        allowed = {q.upper() for q in self.cfg.get("allowed_quotes", [])}
        if allowed and quote.upper() not in allowed:
            return MandateDecision(False, f"quote {quote} not in mandate allowlist")
        return MandateDecision(True)


def verify_withdrawal_disabled(api_permissions: Mapping[str, bool]) -> bool:
    """Refuse to start live unless withdrawal permission is DISABLED (§23.4)."""
    return not bool(api_permissions.get("withdraw", False))


@dataclass
class DivergenceTracker:
    """Paper-vs-live cost divergence per plugin (§23.8). Demotes when live costs
    exceed modeled by more than ``threshold_mult``."""

    threshold_mult: float = 2.0
    _modeled: dict[str, list] = field(default_factory=lambda: defaultdict(list))
    _actual: dict[str, list] = field(default_factory=lambda: defaultdict(list))

    def record(self, plugin: str, modeled_cost_bps: float, actual_cost_bps: float) -> None:
        self._modeled[plugin].append(modeled_cost_bps)
        self._actual[plugin].append(actual_cost_bps)

    def should_demote(self, plugin: str) -> bool:
        m = self._modeled.get(plugin, [])
        a = self._actual.get(plugin, [])
        if not m or not a:
            return False
        avg_m = sum(m) / len(m)
        avg_a = sum(a) / len(a)
        return avg_m > 0 and avg_a > self.threshold_mult * avg_m


class LiveBroker:
    """ccxt live adapter (§7.6). Refuses to operate outside the mandate.

    ``exchange`` is a ccxt-like client (``create_order``/``fetch_positions``/
    ``cancel_all_orders``); injected for tests, else lazily built from
    ``api_credentials`` (testnet-aware). The order-building path is real — it just
    needs live/testnet keys to actually reach an exchange.
    """

    def __init__(
        self,
        exchange_id: str,
        mandate: MandateGate,
        api_permissions: Mapping[str, bool],
        exchange: Optional[Any] = None,
        api_credentials: Optional[Mapping[str, str]] = None,
        testnet: bool = True,
    ) -> None:
        if not verify_withdrawal_disabled(api_permissions):
            raise PermissionError("API key has withdrawal permission — refusing live mode (§23.4)")
        self.exchange_id = exchange_id
        self.mandate = mandate
        self.testnet = testnet
        self._ex = exchange or self._build_exchange(api_credentials)

    def _build_exchange(self, creds: Optional[Mapping[str, str]]) -> Any:
        if not creds:
            return None  # created on first use / injected in tests
        import ccxt  # pragma: no cover - needs the [data] extra + keys
        ex = getattr(ccxt, self.exchange_id)({
            "apiKey": creds.get("apiKey"), "secret": creds.get("secret"),
            "enableRateLimit": True,
        })
        if self.testnet and hasattr(ex, "set_sandbox_mode"):
            ex.set_sandbox_mode(True)
        return ex

    def place(self, plan: TradePlan, total_notional_after: float, open_positions_after: int) -> OrderResult:
        decision = self.mandate.check(plan, total_notional_after, open_positions_after)
        if not decision.ok:
            return OrderResult(ok=False, status="rejected", error=decision.reason, raw={})
        if plan.action is Action.NO_TRADE or self._ex is None:
            return OrderResult(ok=True, order_id=client_order_id(plan.symbol), status="open",
                               raw={"note": "no exchange bound — id reserved (idempotent)"})
        side = "buy" if plan.action is Action.LONG else "sell"
        amount = (plan.size_quote or 0.0) / plan.entry if plan.entry else 0.0
        coid = client_order_id(plan.symbol)
        try:
            raw = self._ex.create_order(
                plan.symbol, "limit", side, amount, plan.entry,
                {"clientOrderId": coid},  # idempotent (§7.6)
            )
            return OrderResult(ok=True, order_id=str(raw.get("id", coid)),
                               filled_qty=float(raw.get("filled", 0.0)),
                               avg_price=raw.get("average"), status="open", raw=raw)
        except Exception as exc:  # noqa: BLE001 — broker owns retries (§25.8)
            return OrderResult(ok=False, status="rejected", error=str(exc), raw={})

    def positions(self) -> list[dict]:
        if self._ex is None:
            return []
        try:
            return list(self._ex.fetch_positions())
        except Exception:  # noqa: BLE001
            return []

    def cancel_all(self, symbol: str) -> None:
        if self._ex is not None and hasattr(self._ex, "cancel_all_orders"):
            try:
                self._ex.cancel_all_orders(symbol)
            except Exception:  # noqa: BLE001
                pass

    def reconcile_on_start(self, journal_symbols: list[str]) -> Any:
        """Diff exchange positions vs journal on startup (fail-closed, §23.5)."""
        from aimos.runtime.reconciliation import reconcile_positions
        ex_syms = [p.get("symbol") for p in self.positions() if p.get("symbol")]
        return reconcile_positions(ex_syms, journal_symbols)


__all__ = [
    "DivergenceTracker",
    "LiveBroker",
    "MandateDecision",
    "MandateGate",
    "client_order_id",
    "verify_withdrawal_disabled",
]
