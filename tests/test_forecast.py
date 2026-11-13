from datetime import datetime, timedelta, timezone

from backend.forecast import baseline
from backend.models import CGMReading

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def trace(values, step=5):
    return [CGMReading(t=T0 + timedelta(minutes=i * step), mgdl=v) for i, v in enumerate(values)]


def test_flat_trace_gives_flat_forecast():
    h = trace([120] * 6)
    fc = baseline.forecast(h, h[-1].t)
    assert fc is not None
    assert all(abs(m - 120) < 0.5 for m in fc.mean)
    assert baseline.arrow(baseline.trend(h, h[-1].t)) == "→"


def test_linear_fall_extrapolated_within_tolerance():
    h = trace([150 - 2 * 5 * i for i in range(6)])  # -2 mg/dL/min
    now = h[-1].t
    fc = baseline.forecast(h, now)
    last = h[-1].mgdl
    # Damped: forecast falls, but less than the undamped line.
    assert fc.mean[0] < last
    assert abs(fc.mean[0] - (last - 20)) < 1.0  # first 10 min undamped
    assert last - 60 < fc.mean[2] < last - 40
    assert all(lo < m < hi for lo, m, hi in zip(fc.lo, fc.mean, fc.hi))
    assert baseline.arrow(baseline.trend(h, now)) == "↓"


def test_sensor_gap_gives_no_forecast():
    h = trace([120, 118])
    assert baseline.forecast(h, h[-1].t) is None
    # Old data only: last reading 30 min ago.
    h = trace([120] * 6)
    assert baseline.forecast(h, h[-1].t + timedelta(minutes=30)) is None
