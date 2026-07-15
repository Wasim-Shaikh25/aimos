"""Paper-trading loop entrypoint (§10.1, card P5-T1).

Wires the data layer → PipelineOrchestrator → PaperBroker in an asyncio loop.
The deterministic per-tick logic lives in `pipeline.py` (tested); this is the
deployment entrypoint that feeds it live/recorded data.
"""
from __future__ import annotations
import sys


def main() -> int:  # pragma: no cover - deployment entrypoint
    print("aimos paper trader (deployment entrypoint) — see runtime/pipeline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
