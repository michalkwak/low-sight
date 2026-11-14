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
    driving: bool = False  # in_vehicle and role != "passenger"
    in_vehicle: bool = False  # from the phone
    role: Literal["driver", "passenger", "unknown"] = "unknown"  # from a glasses session
    p_driver: float = 0.5  # smoothed seat score from the last glasses session
    speed_kmh: float | None = None
    car_connected: bool = False
    phone_stale: bool = True
    source: Literal["phone", "forced"] = "phone"
    since: datetime
    seat_checking: bool = False  # camera frames are arriving (a seat check is running)


class Alert(BaseModel):
    level: AlertLevel = "NONE"
    title: str = ""
    line: str = ""
    speak: str | None = None  # None → deliver silently (already spoken this episode)
    acked: bool = False
    id: str = ""  # new for every alert (and for the PULL_OVER repeat): speak/notify once per id
    since: datetime | None = None  # demo time the alert was raised
    until: datetime | None = None  # RECOVERING: end of the wait countdown (demo time)
    spoken: bool = False  # a phone (or stage audio) reported speaking this id; the HUD then stays quiet


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
    force_driving: Literal["on", "off", "auto"] = "auto"  # control-panel overrides, shown on /control
    force_role: Literal["driver", "passenger", "auto"] = "auto"
