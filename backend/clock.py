"""DemoClock: real or accelerated time with pause/seek/reset.

Every time-dependent component must call ``clock.now()``, never ``datetime.now()``.
"""
import time
from datetime import datetime, timedelta, timezone


class DemoClock:
    def __init__(self, start: datetime | None = None, speed: float = 30.0, wall=time.monotonic):
        self._wall = wall
        self._start = start or datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        self.speed = speed
        self.reset()

    def reset(self, start: datetime | None = None) -> None:
        if start is not None:
            self._start = start
        self._base_demo = self._start
        self._base_wall = self._wall()
        self.paused = False

    def now(self) -> datetime:
        if self.paused:
            return self._base_demo
        elapsed = (self._wall() - self._base_wall) * self.speed
        return self._base_demo + timedelta(seconds=elapsed)

    def _rebase(self) -> None:
        self._base_demo = self.now()
        self._base_wall = self._wall()

    def set_speed(self, speed: float) -> None:
        self._rebase()
        self.speed = speed

    def pause(self) -> None:
        if not self.paused:
            self._rebase()
            self.paused = True

    def resume(self) -> None:
        if self.paused:
            self._base_wall = self._wall()
            self.paused = False

    def seek(self, minutes: float) -> None:
        """Jump relative to now (positive = forward)."""
        self._rebase()
        self._base_demo += timedelta(minutes=minutes)

    def seek_to(self, t: datetime) -> None:
        self._rebase()
        self._base_demo = t

    @property
    def start(self) -> datetime:
        return self._start
