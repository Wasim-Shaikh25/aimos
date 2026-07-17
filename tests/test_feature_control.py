"""Runtime feature toggles via UI (API) and Telegram — safe flags only, live locked."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from aimos.core.config import load_params
from aimos.runtime.features import FeatureController
from aimos.runtime.serve import build_app


def test_controller_toggles_safe_flags_and_locks_dangerous():
    calls = {"n": 0}
    p = load_params()
    fc = FeatureController(p, rebuild=lambda: calls.__setitem__("n", calls["n"] + 1))

    r = fc.set("scalp", False)
    assert r["ok"] and p.features.model_dump()["scalp_enabled"] is False
    r = fc.set("cross_exchange", True)
    assert r["ok"] and p.features.model_dump()["cross_exchange_enabled"] is True
    assert p.plugins["cross_exchange_arb"].enabled is True   # single toggle arms the plugin
    assert calls["n"] == 2                                    # rebuild fired each time

    # dangerous flags are refused
    for locked in ("live", "mode", "mandate", "multi_venue_live", "market_making"):
        assert fc.set(locked, True)["ok"] is False
    # unknown flag refused
    assert fc.set("please_send_money", True)["ok"] is False


def test_api_feature_toggle_is_confirm_gated_and_locks_live():
    app = build_app(offline=True)
    with TestClient(app) as c:
        time.sleep(0.5)
        assert "cross_exchange" in c.get("/api/features").json()["toggleable"]
        # no confirm → 403
        assert c.post("/api/control/feature", json={"name": "scalp", "enabled": False}).status_code == 403
        # confirmed safe toggle → ok
        ok = c.post("/api/control/feature",
                    json={"confirm": "CONFIRM", "name": "cross_exchange", "enabled": True})
        assert ok.status_code == 200 and ok.json()["enabled"] is True
        # confirmed LOCKED flag → 400 (refused)
        bad = c.post("/api/control/feature",
                     json={"confirm": "CONFIRM", "name": "live", "enabled": True})
        assert bad.status_code == 400 and "LOCKED" in bad.json()["detail"]


def test_telegram_enable_disable_features():
    from aimos.core.clock import LiveClock
    from aimos.telegram.bot import CommandRouter
    from aimos.telegram.security import ChatWhitelist, NonceStore

    p = load_params()
    fc = FeatureController(p, rebuild=lambda: None)
    router = CommandRouter(ChatWhitelist({111}), NonceStore(LiveClock()), feature_controller=fc)

    assert "toggleable" in router.handle(111, "/features")

    def confirmed(cmd):  # /enable and /disable are two-step (nonce) commands
        reply = router.handle(111, cmd)
        nonce = reply.split("/confirm ")[1].split(" ")[0]
        return router.handle(111, f"/confirm {nonce}")

    assert "enabled" in confirmed("/enable cross_exchange")
    assert p.features.model_dump()["cross_exchange_enabled"] is True
    assert "disabled" in confirmed("/disable scalp")
    assert "LOCKED" in confirmed("/enable live")           # locked flag refused on TG too
    assert router.handle(999, "/enable scalp") is None      # unauthorized chat → silent
