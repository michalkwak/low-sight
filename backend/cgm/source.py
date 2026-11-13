"""CGM sources. A source exposes ``readings_until(now)`` returning every reading
whose timestamp is <= ``now``."""
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd

from backend.models import CGMReading


class CGMSource(Protocol):
    def readings_until(self, now: datetime) -> list[CGMReading]: ...


class ReplaySource:
    """Replays a scenario DataFrame (``minute``, ``mgdl``) anchored at ``start``."""

    def __init__(self, df: pd.DataFrame, start: datetime):
        self.start = start
        self._readings = [
            CGMReading(t=start + timedelta(minutes=float(m)), mgdl=float(v))
            for m, v in zip(df["minute"], df["mgdl"])
        ]

    def readings_until(self, now: datetime) -> list[CGMReading]:
        return [r for r in self._readings if r.t <= now]

    @property
    def end(self) -> datetime:
        return self._readings[-1].t if self._readings else self.start

    def first_crossing(self, below: float) -> datetime | None:
        for r in self._readings:
            if r.mgdl < below:
                return r.t
        return None
