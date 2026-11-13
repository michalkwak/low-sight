"""Shared data model. Everything is stored in mg/dL; convert only for display."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AlertLevel = Literal["NONE", "LOW_SOON", "PRE_DRIVE", "PULL_OVER", "RECOVERING"]


class CGMReading(BaseModel):
    t: datetime
    mgdl: float


class Forecast(BaseModel):
    t0: datetime
    horizons_min: list[int]  # e.g. [10, 20, 30]
    mean: list[float]
    lo: list[float]
    hi: list[float]


class DrivingState(BaseModel):
    driving: bool = False
    p_driver: float = 0.0
    source: Literal["vision", "forced"] = "vision"
    since: datetime


class Alert(BaseModel):
    level: AlertLevel = "NONE"
    title: str = ""
    line: str = ""
    speak: str | None = None
    acked: bool = False
    id: str = ""


class AppState(BaseModel):
    now: datetime
    reading: CGMReading | None
    trend_mgdl_min: float
    arrow: str
    forecast: Forecast | None
    driving: DrivingState
    alert: Alert
    history: list[CGMReading]  # last 3 h, for the sparkline
    units: Literal["mmol", "mgdl"]
    scenario: str = ""
    speed: float = 1.0
    paused: bool = False
