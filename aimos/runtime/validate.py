"""End-to-end live/testnet integration validation (§23.8 gate 3).

Runs the real account+order path against an exchange (testnet by default) and
produces a per-capability PASS/FAIL report — so you can confirm the development is
actually wired against a real exchange, not just mocks, before risking any money.
On an all-pass it marks the go-live ladder's testnet gate.

Capabilities checked: authenticate → fetch balance (read-only) → withdrawals
disabled → place a tiny order → cancel it → reconcile vs journal. Pure enough to
test with a mock; runs for real on the operator's machine. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aimos.account.preflight import preflight_check
from aimos.runtime.testnet_probe import run_testnet_probe


@dataclass
class Report:
    steps: list = field(default_factory=list)   # [{"name","ok","detail"}]
    all_ok: bool = False

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append({"name": name, "ok": bool(ok), "detail": detail})

    def render(self) -> str:
        lines = [f"{'✅' if s['ok'] else '❌'} {s['name']}: {s['detail']}" for s in self.steps]
        lines.append(f"\n{'ALL PASS' if self.all_ok else 'FAILED'} "
                     f"({sum(s['ok'] for s in self.steps)}/{len(self.steps)})")
        return "\n".join(lines)


def validate_integration(
    venue: str, creds: dict, broker, ladder=None, symbol: str = "BTC/USDT",
    notional_usdt: float = 11.0, client_factory=None,
) -> Report:
    """Run the capability checklist against one venue. ``broker`` is a LiveBroker
    (testnet). Returns a Report; marks the testnet gate only if everything passes."""
    rep = Report()

    pf = preflight_check([venue], {venue.lower(): creds}, client_factory=client_factory).get(venue, {})
    rep.add("authenticate + fetch balance", pf.get("connected", False),
            f"USDT free {pf.get('usdt_free', '?')}" if pf.get("connected") else pf.get("error", "no connect"))
    rep.add("withdrawals disabled (§23.4)", pf.get("withdrawal_disabled", False),
            "key cannot withdraw" if pf.get("withdrawal_disabled") else "⚠️ key CAN withdraw — refused")

    # place → cancel → reconcile (do NOT mark the gate here; aggregate first)
    probe = run_testnet_probe(broker, ladder=None, symbol=symbol, notional_usdt=notional_usdt)
    rep.add("place order", probe.get("ok", False), probe.get("order_id", probe.get("error", "")))
    rep.add("cancel + reconcile", probe.get("ok", False), str(probe.get("reconcile", probe.get("error", ""))))

    rep.all_ok = all(s["ok"] for s in rep.steps)
    if rep.all_ok and ladder is not None:
        ladder.set_marker("testnet_started")  # start the 1-week testnet clock
    return rep


__all__ = ["Report", "validate_integration"]
