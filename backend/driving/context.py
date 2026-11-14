"""Driving context: phone says "in a moving car", a short glasses session says
"you're the driver" (or passenger). Combined into one DrivingState.

Rules:
- ``in_vehicle`` comes from the phone (or the control-panel override).
- ``role`` starts as "unknown". A glasses session that classifies the seat sets
  it for the current trip. A confirmation made while parked carries over to a
  trip that starts within TRIP_END_S. The role resets when the trip ends.
- ``driving = in_vehicle and role != "passenger"``: an unconfirmed wearer in a
  moving car is treated as possibly driving (missing a real driver is worse
  than warning a passenger).
"""
from datetime import datetime
from typing import Literal

from backend.config import settings
from backend.driving.phone import PhoneSignal, VehicleTracker
from backend.models import DrivingState
from backend.vision.driving_state import Seat, SeatTracker

Force = Literal["auto", "on", "off"]
ForceRole = Literal["auto", "driver", "passenger"]
Role = Literal["driver", "passenger", "unknown"]
RoleSource = Literal["none", "camera", "wearer"]


class DrivingContext:
    def __init__(self) -> None:
        self.vehicle = VehicleTracker()
        self.seat = SeatTracker()
        self.force_vehicle: Force = "auto"
        self.force_role: ForceRole = "auto"
        self.reset()

    def reset(self) -> None:
        self.vehicle.reset()
        self.seat.reset()
        self._role: Role = "unknown"
        self._role_at: float | None = None
        self._role_source: RoleSource = "none"
        self._was_in_vehicle = False
        self._frame_at: float | None = None

    # ---- inputs ----
    def on_phone(self, sig: PhoneSignal) -> None:
        self.vehicle.update(sig)

    def start_seat_check(self) -> None:
        """A new glasses session (camera connection): smooth its frames from scratch, so
        frames from an earlier session can't help or hinder this decision. The role
        already decided for this trip stays until the new session decides."""
        self.seat.reset()
        self._frame_at = None

    def end_seat_check(self) -> None:
        self._frame_at = None

    def on_frame(self, p_driver: float, wall_s: float) -> Seat | None:
        self._frame_at = wall_s
        seat = self.seat.update(p_driver, wall_s)
        if seat is not None:
            self._set_role(seat, wall_s, "camera")
        return seat

    def confirm_role(self, role: Seat, wall_s: float) -> None:
        """The wearer says which seat they're in (voice via Meta AI, or the phone page).
        Same effect as a decided seat check: it holds for this trip, carries into a trip
        that starts within TRIP_END_S, and resets when the trip ends. This is the fallback
        when no camera check runs (web apps can't use the glasses camera). While a camera
        session keeps deciding, its result overwrites this on the next frame: the camera is
        the authority when it runs."""
        self._set_role(role, wall_s, "wearer")

    def _set_role(self, role: Role, wall_s: float | None, source: RoleSource) -> None:
        self._role, self._role_at, self._role_source = role, wall_s, source

    def tick(self, wall_s: float) -> None:
        self.vehicle.tick(wall_s)
        now_in = self.in_vehicle
        if self._was_in_vehicle and not now_in:
            self._set_role("unknown", None, "none")  # trip ended
            self.seat.reset()
        elif (
            not now_in
            and self._role_at is not None
            and wall_s - self._role_at >= settings.TRIP_END_S
        ):
            self._set_role("unknown", None, "none")  # parked confirmation expired
        self._was_in_vehicle = now_in

    # ---- outputs ----
    @property
    def in_vehicle(self) -> bool:
        if self.force_vehicle == "on":
            return True
        if self.force_vehicle == "off":
            return False
        return self.vehicle.in_vehicle

    @property
    def role(self) -> Role:
        return self._role if self.force_role == "auto" else self.force_role

    @property
    def driving(self) -> bool:
        return self.in_vehicle and self.role != "passenger"

    def snapshot(self, since: datetime, wall_s: float) -> DrivingState:
        last = self.vehicle.last
        forced = self.force_vehicle != "auto" or self.force_role != "auto"
        return DrivingState(
            driving=self.driving,
            in_vehicle=self.in_vehicle,
            role=self.role,
            p_driver=round(self.seat.ema, 3),
            speed_kmh=None if last is None or last.speed_kmh is None else round(last.speed_kmh, 1),
            car_connected=bool(last and last.car_connected),
            phone_stale=self.vehicle.stale(wall_s),
            source="forced" if forced else "phone",
            since=since,
            seat_checking=self._frame_at is not None and wall_s - self._frame_at < 3.0,
            role_source="forced" if self.force_role != "auto" else self._role_source,
        )
