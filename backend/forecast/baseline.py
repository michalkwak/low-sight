"""Baseline forecaster: weighted linear fit over the last 20 min, damped
extrapolation to +10/+20/+30 min, fixed (or CITY-calibrated) error band."""
from datetime import datetime, timedelta

import numpy as np

from backend.models import CGMReading, Forecast

HORIZONS = [10, 20, 30]
DEFAULT_BAND = [6.0, 12.0, 20.0]  # ± mg/dL; replace with CITY residual quantiles
DAMPING = 0.85  # slope multiplier per 10 min
FIT_WINDOW_MIN = 20
TREND_WINDOW_MIN = 15
MIN_POINTS = 3
FLOOR_MGDL, CEIL_MGDL = 40.0, 400.0  # CGM reporting range: steep drops can't forecast below 40


def _clamp(v: float) -> float:
    return round(min(max(v, FLOOR_MGDL), CEIL_MGDL), 1)


def _recent(history: list[CGMReading], now: datetime, window_min: float) -> list[CGMReading]:
    cutoff = now - timedelta(minutes=window_min, seconds=1)
    return [r for r in history if cutoff <= r.t <= now]


def _anchored(history: list[CGMReading], now: datetime, window_min: float) -> list[CGMReading]:
    """The window ending at the latest reading (not at ``now``), so a fit uses the same
    points (e.g. 5 for 20 min) until the next reading arrives instead of shifting between
    readings. Callers check for a sensor gap against ``now`` first."""
    past = [r for r in history if r.t <= now]
    return _recent(past, past[-1].t, window_min) if past else []


def _weighted_slope(pts: list[CGMReading], ref: datetime) -> tuple[float, float]:
    """Return (slope mg/dL/min, intercept at ``ref``) with recent points weighted higher."""
    x = np.array([(r.t - ref).total_seconds() / 60 for r in pts])
    y = np.array([r.mgdl for r in pts])
    w = np.linspace(1.0, 2.0, len(pts))
    slope, intercept = np.polyfit(x, y, 1, w=np.sqrt(w))
    return float(slope), float(intercept)


def trend(history: list[CGMReading], now: datetime) -> float | None:
    if len(_recent(history, now, TREND_WINDOW_MIN)) < 2:
        return None
    pts = _anchored(history, now, TREND_WINDOW_MIN)
    slope, _ = _weighted_slope(pts, pts[-1].t)
    return slope


def arrow(slope: float | None) -> str:
    if slope is None:
        return ""
    if slope <= -3:
        return "⇊"
    if slope <= -2:
        return "↓"
    if slope <= -1:
        return "↘"
    if slope < 1:
        return "→"
    if slope < 2:
        return "↗"
    if slope < 3:
        return "↑"
    return "⇈"


def forecast(history: list[CGMReading], now: datetime, band: list[float] | None = None) -> Forecast | None:
    if len(_recent(history, now, FIT_WINDOW_MIN)) < MIN_POINTS:
        return None  # sensor gap → HUD shows "No CGM data"
    pts = _anchored(history, now, FIT_WINDOW_MIN)
    t0 = pts[-1].t
    slope, intercept = _weighted_slope(pts, t0)
    band = band or DEFAULT_BAND

    mean, lo, hi = [], [], []
    for h, b in zip(HORIZONS, band):
        # Integrate a slope that decays by DAMPING every 10 min.
        value, s = intercept, slope
        for _ in range(h // 10):
            value += s * 10
            s *= DAMPING
        mean.append(_clamp(value))
        lo.append(_clamp(value - b))
        hi.append(_clamp(value + b))
    return Forecast(t0=t0, horizons_min=list(HORIZONS), mean=mean, lo=lo, hi=hi)
