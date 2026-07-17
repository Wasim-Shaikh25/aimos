#!/usr/bin/env python
"""CLI: place ONE tiny order on an exchange testnet to validate the live path
(§23.8 gate 3). Requires testnet keys (AIMOS_SECRETS_FILE or env) and a testnet
mandate enabled in config/mandate.yaml. Marks the go-live ladder's testnet gate.

    python -m scripts.testnet_order --exchange binance --symbol BTC/USDT

Places against TESTNET only (set_sandbox_mode). Keys must have withdrawals off.
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AIMOS testnet order probe.")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--notional", type=float, default=11.0)
    args = ap.parse_args(argv)

    from aimos.account.secrets import load_secrets
    from aimos.core.config import load_params
    from aimos.runtime.golive import GoLiveLadder
    from aimos.runtime.testnet_probe import build_testnet_broker, run_testnet_probe

    params = load_params()
    creds = load_secrets(params.model_dump().get("secrets", {}).get("file", ""),
                         venues=[args.exchange]).get(args.exchange.lower())
    if not creds:
        print(f"no testnet keys for {args.exchange}. Set AIMOS_SECRETS_FILE or "
              f"AIMOS_KEY_{args.exchange.upper()}/AIMOS_SECRET_{args.exchange.upper()}.")
        return 2
    if not params.model_dump().get("mandate", {}).get("enabled"):
        print("mandate not enabled — set a small TESTNET mandate in config/mandate.yaml first.")
        return 3
    broker = build_testnet_broker(args.exchange, params, creds)
    result = run_testnet_probe(broker, GoLiveLadder(), symbol=args.symbol,
                               notional_usdt=args.notional)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
