"""Seat classification from glasses-camera frames: EMA smoothing over per-frame
p_driver, then a held threshold to decide "driver" or "passenger".

Glasses sessions last at most 3 minutes and only start when the wearer opens the
app, so vision is a one-off *confirmation* of the seat, not a continuous
driving detector. The phone (backend/driving/) detects the trip itself.

Timing uses wall-clock seconds passed in by the caller (frames arrive in real
time, independent of the accelerated CGM demo clock)."""
from typing import Literal

from backend.config import settings

Seat = Literal["driver", "passenger"]


class SeatTracker:
    def __init__(self, alpha=None, enter_p=None, exit_p=None, hold_s=None):
        self.alpha = alpha if alpha is not None else settings.EMA_ALPHA
        self.enter_p = enter_p if enter_p is not None else settings.ENTER_P
        self.exit_p = exit_p if exit_p is not None else settings.EXIT_P
        self.hold_s = hold_s if hold_s is not None else settings.ENTER_S
        self.reset()

    def reset(self) -> None:
        self.ema = 0.5  # undecided until frames arrive
        self.p_last: float | None = None
        self._pending: Seat | None = None
        self._pending_since: float | None = None

    def update(self, p_driver: float, wall_s: float) -> Seat | None:
        """Feed one frame. Returns a seat once the EMA has held past a threshold
        for ``hold_s`` seconds, otherwise None. A single odd frame never decides."""
        if self.p_last is None:
            self.ema = p_driver
        else:
            self.ema = self.alpha * p_driver + (1 - self.alpha) * self.ema
        self.p_last = p_driver

        cand: Seat | None = (
            "driver" if self.ema > self.enter_p else "passenger" if self.ema < self.exit_p else None
        )
        if cand != self._pending:
            self._pending, self._pending_since = cand, wall_s
        if cand is not None and wall_s - self._pending_since >= self.hold_s:
            return cand
        return None
