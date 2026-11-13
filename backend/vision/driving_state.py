"""Driving state: EMA smoothing + hysteresis over per-frame p_driver, plus a
control-panel override (force on/off/auto).

Timing uses wall-clock seconds passed in by the caller (frames arrive in real
time, independent of the accelerated CGM demo clock)."""
from datetime import datetime
from typing import Literal

from backend.config import settings
from backend.models import DrivingState

Force = Literal["auto", "on", "off"]


class DrivingStateTracker:
    def __init__(self, alpha=None, enter_p=None, enter_s=None, exit_p=None, exit_s=None):
        self.alpha = alpha if alpha is not None else settings.EMA_ALPHA
        self.enter_p = enter_p if enter_p is not None else settings.ENTER_P
        self.enter_s = enter_s if enter_s is not None else settings.ENTER_S
        self.exit_p = exit_p if exit_p is not None else settings.EXIT_P
        self.exit_s = exit_s if exit_s is not None else settings.EXIT_S
        self.force: Force = "auto"
        self.reset()

    def reset(self) -> None:
        self.ema = 0.0
        self.p_last = 0.0
        self.vision_driving = False
        self._cond_since: float | None = None  # wall time the pending transition condition began

    def update(self, p_driver: float, wall_s: float) -> bool:
        """Feed one frame's probability. Returns the vision-derived driving flag."""
        self.p_last = p_driver
        self.ema = self.alpha * p_driver + (1 - self.alpha) * self.ema
        if not self.vision_driving:
            cond, hold = self.ema > self.enter_p, self.enter_s
        else:
            cond, hold = self.ema < self.exit_p, self.exit_s
        if cond:
            if self._cond_since is None:
                self._cond_since = wall_s
            if wall_s - self._cond_since >= hold:
                self.vision_driving = not self.vision_driving
                self._cond_since = None
        else:
            self._cond_since = None
        return self.vision_driving

    @property
    def driving(self) -> bool:
        if self.force == "on":
            return True
        if self.force == "off":
            return False
        return self.vision_driving

    def snapshot(self, since: datetime) -> DrivingState:
        return DrivingState(
            driving=self.driving,
            p_driver=round(self.ema, 3),
            source="vision" if self.force == "auto" else "forced",
            since=since,
        )
