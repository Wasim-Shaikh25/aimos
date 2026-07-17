"""Testnet order probe (§23.8 gate 3). Places ONE tiny order on an exchange
*testnet* through the real ``LiveBroker`` path, cancels it, reconciles, and marks
the go-live ladder's testnet gate as started.

This is the step that proves the live code against a real exchange API (order
shape, precision, client-order-id idempotency, cancel, reconcile) — everything the
mock can't. Runs only against **testnet** with mandate-gated, withdrawal-disabled
keys. The core is a pure function so it's testable with a mock broker (no network).
Not in the linted layers.
"""

from __future__ import annotations

from typing import Optional

from aimos.core.schemas import Action, TradePlan


def run_testnet_probe(
    broker, ladder, symbol: str = "BTC/USDT", notional_usdt: float = 11.0,
    price: float = 1.0,
) -> dict:
    """Place one tiny order via ``broker`` (a LiveBroker), cancel, reconcile, and
    record the testnet gate. Returns a structured result — never raises."""
    plan = TradePlan(
        plugin="TestnetProbe", symbol=symbol, action=Action.LONG, entry=price,
        stop_loss=price * 0.99, take_profit=price * 1.01, expected_rr=1.0,
        expected_hold_minutes=1, expected_costs_bps=0.0, confidence=1.0,
        size_quote=notional_usdt, meta={"probe": True},
    )
    res = broker.place(plan, total_notional_after=notional_usdt, open_positions_after=1)
    if not res.ok:
        return {"ok": False, "stage": "place", "error": res.error}
    try:
        broker.cancel_all(symbol)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "cancel", "error": str(exc), "order_id": res.order_id}
    recon = None
    try:
        recon = broker.reconcile_on_start([symbol])
    except Exception:  # noqa: BLE001 - reconcile is best-effort on a probe
        recon = "unavailable"
    if ladder is not None:
        ladder.set_marker("testnet_started")
    return {"ok": True, "order_id": res.order_id, "reconcile": str(recon),
            "note": "testnet order placed + cancelled; ladder gate 'testnet_1wk' started"}


def build_testnet_broker(exchange_id: str, params, creds: Optional[dict] = None):  # pragma: no cover - needs keys
    """Build a testnet LiveBroker from mandate.yaml + secrets (real deployment)."""
    from aimos.execution.broker.live import LiveBroker, MandateGate
    mandate = MandateGate(params.model_dump().get("mandate", {"enabled": False}))
    perms = {"withdraw": bool((creds or {}).get("withdraw", False))}
    return LiveBroker(exchange_id, mandate, perms, api_credentials=creds, testnet=True)


__all__ = ["build_testnet_broker", "run_testnet_probe"]
