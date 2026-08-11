#!/usr/bin/env python
"""CLI: validate the live integration against a real exchange (TESTNET by default).

    python -m scripts.validate_integration --exchange binance          # testnet (free, recommended)
    python -m scripts.validate_integration --exchange binance --mainnet # REAL money — tiny order

Runs: authenticate → balance → withdrawals-disabled → place tiny order → cancel →
reconcile, and prints a PASS/FAIL report. Needs keys (AIMOS_SECRETS_FILE or env)
and a small mandate enabled in config/mandate.yaml. Testnet uses fake funds but the
real API — the right way to confirm the build works before risking money.
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AIMOS live-integration validator.")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--notional", type=float, default=11.0)
    ap.add_argument("--mainnet", action="store_true", help="REAL money (default: testnet)")
    args = ap.parse_args(argv)

    from aimos.account.secrets import load_secrets
    from aimos.core.config import load_params_for_user
    from aimos.runtime.golive import GoLiveLadder
    from aimos.runtime.testnet_probe import build_testnet_broker
    from aimos.runtime.validate import validate_integration
    from aimos.settings import SettingsStore

    params = load_params_for_user()
    storage_cfg = params.model_dump().get("storage", {}) or {}
    store = SettingsStore("default", database_url=storage_cfg.get("database_url", ""))

    vl = args.exchange.lower()
    creds = store.get_exchange_credentials(vl)
    if not creds:
        legacy = load_secrets(params.model_dump().get("secrets", {}).get("file", ""),
                              venues=[args.exchange])
        creds = legacy.get(vl)
    if not creds:
        print(f"no keys for {args.exchange}. Add them in Settings → Exchanges, or set "
              f"AIMOS_SECRETS_FILE / AIMOS_KEY_{args.exchange.upper()}.")
        return 2
    if not params.model_dump().get("mandate", {}).get("enabled"):
        print("mandate not enabled — set a small mandate in config/mandate.yaml first.")
        return 3
    if args.mainnet:
        print("⚠️  MAINNET — this places a REAL order with REAL money. Ctrl-C to abort (5s)…")
        import time
        time.sleep(5)

    broker = build_testnet_broker(args.exchange, params, creds)
    broker.testnet = False if args.mainnet else bool(creds.get("testnet", True))
    rep = validate_integration(args.exchange, creds, broker, ladder=GoLiveLadder(),
                               symbol=args.symbol, notional_usdt=args.notional)
    print(rep.render())
    return 0 if rep.all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
