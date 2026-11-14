from datetime import datetime, timezone

import pytest

from backend.config import settings
from backend.driving.context import DrivingContext
from backend.driving.phone import PhoneSignal, VehicleTracker
from backend.vision.clip_detector import seat_score
from backend.vision.driving_state import SeatTracker

T = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def feed_seat(tr, p, start, seconds, fps=2):
    out = None
    for i in range(int(seconds * fps)):
        out = tr.update(p, start + i / fps) or out
    return out


# ---- seat check (glasses session) ----
def test_one_false_positive_frame_does_not_decide():
    tr = SeatTracker()
    feed_seat(tr, 0.5, 0, 5)
    assert tr.update(0.99, 5.0) is None
    assert feed_seat(tr, 0.5, 5.5, 5) is None


def test_steady_driver_frames_confirm_within_session():
    tr = SeatTracker()
    assert feed_seat(tr, 0.95, 0, 6) == "driver"
    assert 6 < settings.SESSION_MAX_S


def test_passenger_frames_confirm_passenger():
    assert feed_seat(SeatTracker(), 0.05, 0, 6) == "passenger"


def test_indoor_frames_never_confirm_passenger():
    # A kitchen has p(driver) ≈ 0, but it says nothing about the seat. Deciding "passenger"
    # from it would silence driving alerts on a trip that starts within TRIP_END_S.
    kitchen = {"driver": 0.0, "passenger": 0.0, "other": 1.0}
    assert seat_score(kitchen) == 0.5
    assert feed_seat(SeatTracker(), seat_score(kitchen), 0, 60) is None
    # In a car, the score is p(driver), so real seat views still decide both ways.
    assert seat_score({"driver": 0.9, "passenger": 0.1, "other": 0.0}) == pytest.approx(0.9)
    assert seat_score({"driver": 0.05, "passenger": 0.95, "other": 0.0}) == pytest.approx(0.05)


# ---- phone trip detection ----
def drive(vt, kmh, start, seconds, car=False):
    for t in range(int(seconds)):
        vt.update(PhoneSignal(speed_kmh=kmh, car_connected=car, wall_s=start + t))
    return vt.in_vehicle


def test_speed_must_hold_before_trip_starts():
    vt = VehicleTracker()
    assert drive(vt, 30, 0, 5) is False  # running for a bus doesn't count
    assert drive(vt, 30, 5, 10) is True


def test_car_connection_starts_trip_immediately():
    vt = VehicleTracker()
    assert drive(vt, 0, 0, 1, car=True) is True


def test_traffic_light_stop_does_not_end_trip():
    vt = VehicleTracker()
    drive(vt, 50, 0, 20)
    assert drive(vt, 0, 20, 90) is True  # 90 s at a red light
    assert drive(vt, 0, 110, settings.TRIP_END_S + 5) is False


def test_silent_phone_holds_then_ends_trip():
    vt = VehicleTracker()
    drive(vt, 50, 0, 20)
    assert vt.tick(60) is True
    assert vt.tick(20 + settings.TRIP_END_S) is False


# ---- combined context ----
def test_unconfirmed_in_car_counts_as_driving():
    ctx = DrivingContext()
    ctx.on_phone(PhoneSignal(speed_kmh=0, car_connected=True, wall_s=0))
    ctx.tick(0)
    assert ctx.role == "unknown" and ctx.driving is True


def test_passenger_confirmation_suppresses_driving_until_trip_ends():
    ctx = DrivingContext()
    ctx.on_phone(PhoneSignal(car_connected=True, wall_s=0))
    for i in range(12):
        ctx.on_frame(0.05, i / 2)
    ctx.tick(6)
    assert ctx.role == "passenger" and ctx.driving is False
    # Trip ends → next trip starts unconfirmed again.
    ctx.on_phone(PhoneSignal(speed_kmh=0, car_connected=False, wall_s=10))
    ctx.on_phone(PhoneSignal(speed_kmh=0, car_connected=False, wall_s=10 + settings.TRIP_END_S))
    ctx.tick(10 + settings.TRIP_END_S)
    assert ctx.in_vehicle is False and ctx.role == "unknown"


def test_parked_confirmation_carries_into_trip():
    ctx = DrivingContext()
    for i in range(12):  # seat check before setting off
        ctx.on_frame(0.95, i / 2)
    ctx.tick(10)
    assert ctx.role == "driver" and ctx.driving is False
    ctx.on_phone(PhoneSignal(car_connected=True, wall_s=60))
    ctx.tick(60)
    assert ctx.role == "driver" and ctx.driving is True


def test_wearer_confirmation_works_like_a_seat_check():
    ctx = DrivingContext()
    ctx.confirm_role("driver", 0)  # parked: "I'm driving"
    ctx.tick(10)
    s = ctx.snapshot(T, 10)
    assert s.role == "driver" and s.role_source == "wearer" and s.driving is False
    ctx.on_phone(PhoneSignal(car_connected=True, wall_s=60))  # trip starts within TRIP_END_S
    ctx.tick(60)
    assert ctx.role == "driver" and ctx.driving is True
    ctx.confirm_role("passenger", 70)  # changes their mind: alerts off for this trip
    assert ctx.driving is False
    ctx.on_phone(PhoneSignal(speed_kmh=0, car_connected=False, wall_s=80))
    ctx.on_phone(PhoneSignal(speed_kmh=0, car_connected=False, wall_s=80 + settings.TRIP_END_S))
    ctx.tick(80 + settings.TRIP_END_S)  # trip over: back to unknown
    assert ctx.role == "unknown" and ctx.snapshot(T, 0).role_source == "none"


def test_role_source_reports_camera_and_override():
    ctx = DrivingContext()
    for i in range(12):
        ctx.on_frame(0.95, i / 2)
    assert ctx.snapshot(T, 6).role_source == "camera"
    ctx.force_role = "passenger"
    assert ctx.snapshot(T, 6).role_source == "forced"


def test_force_overrides():
    ctx = DrivingContext()
    ctx.force_vehicle = "on"
    assert ctx.driving is True
    ctx.force_role = "passenger"
    assert ctx.driving is False
