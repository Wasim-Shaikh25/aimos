"""Watchdog entrypoint (§23.5): heartbeat monitor; 3x miss → restart + alert.

Stub entrypoint for docker-compose. The heartbeat file + liveness loop are wired
to the running orchestrator in deployment.
"""
from __future__ import annotations
import sys


def main() -> int:  # pragma: no cover - deployment entrypoint
    print("aimos watchdog: heartbeat monitor (deployment stub)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
