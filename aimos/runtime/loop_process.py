"""Dedicated trading-loop entrypoint (REQ-13).

Usage:
    export AIMOS_PROCESS=loop
    python -m aimos.runtime.loop_process

This runs only the paper-trading loop + auxiliaries (risk, backup, monitor,
Telegram, stream). The API is served by a separate ``AIMOS_PROCESS=api`` process
that rehydrates state from ``RuntimeStateStore``.
"""

import os


def main() -> None:
    """Build components and run the trading loop forever."""
    os.environ.setdefault("AIMOS_PROCESS", "loop")
    from aimos.runtime import serve  # noqa: E402

    serve.build_app()


if __name__ == "__main__":
    main()
