"""Watchdog — process liveness + heartbeat monitor (§23.5, card P5-T8).

The orchestrator writes a heartbeat file each tick; the watchdog checks its
freshness on an interval. After ``max_missed`` consecutive stale checks it fires
a restart callback + alert (missed heartbeat 3× → restart container, Telegram
alert). Real, testable logic — clock-injected. Not in the linted layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import structlog

from aimos.core.clock import Clock, LiveClock

log = structlog.get_logger(__name__)


class Heartbeat:
    """Written by the running process each tick (§23.5)."""

    def __init__(self, path: Path | str, clock: Optional[Clock] = None) -> None:
        self.path = Path(path)
        self.clock = clock or LiveClock()

    def beat(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.clock.now().isoformat(), encoding="utf-8")

    def last_beat(self) -> Optional[datetime]:
        if not self.path.exists():
            return None
        try:
            return datetime.fromisoformat(self.path.read_text(encoding="utf-8").strip())
        except ValueError:
            return None


@dataclass
class Watchdog:
    heartbeat: Heartbeat
    stale_after_seconds: float
    max_missed: int = 3
    on_restart: Optional[Callable[[], None]] = None
    on_alert: Optional[Callable[[str], None]] = None
    _missed: int = 0

    def is_stale(self, now: datetime) -> bool:
        last = self.heartbeat.last_beat()
        if last is None:
            return True
        return (now - last) > timedelta(seconds=self.stale_after_seconds)

    def check(self, now: Optional[datetime] = None) -> bool:
        """One liveness check. Returns True if a restart was triggered."""
        now = now or self.heartbeat.clock.now()
        if self.is_stale(now):
            self._missed += 1
            log.warning("watchdog_missed_heartbeat", missed=self._missed)
            if self._missed >= self.max_missed:
                msg = f"heartbeat stale {self._missed}x - restarting"
                if self.on_alert:
                    self.on_alert(f"watchdog: {msg}")
                if self.on_restart:
                    self.on_restart()
                self._missed = 0
                return True
        else:
            self._missed = 0
        return False


def main() -> int:  # pragma: no cover - deployment entrypoint
    import os
    hb = Heartbeat(os.environ.get("AIMOS_HEARTBEAT", "state/heartbeat"))
    wd = Watchdog(hb, stale_after_seconds=float(os.environ.get("AIMOS_WD_STALE", "180")))
    log.info("watchdog_started", path=str(hb.path))
    wd.check()  # a real deployment loops with sleep; the check logic is the tested core
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
