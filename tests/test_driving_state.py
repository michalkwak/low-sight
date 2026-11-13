from backend.config import settings
from backend.driving.context import DrivingContext
from backend.driving.phone import PhoneSignal, VehicleTracker
from backend.vision.driving_state import SeatTracker


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


def test_force_overrides():
    ctx = DrivingContext()
    ctx.force_vehicle = "on"
    assert ctx.driving is True
    ctx.force_role = "passenger"
    assert ctx.driving is False
