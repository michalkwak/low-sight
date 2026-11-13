"""In-vehicle detection from phone signals.

Hackathon version: the /phone web page sends GPS speed and a "connected to car"
flag. On a native app these come from Android Activity Recognition
(IN_VEHICLE) / iOS Core Motion (automotive) and the car's Bluetooth or
CarPlay/Android Auto connection; the contract stays the same.

All timing is wall-clock seconds passed in by the caller."""
from dataclasses import dataclass

from backend.config import settings


@dataclass
class PhoneSignal:
    speed_kmh: float | None = None
    car_connected: bool = False
    wall_s: float = 0.0


class VehicleTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.in_vehicle = False
        self.last: PhoneSignal | None = None
        self._moving_since: float | None = None
        self._still_since: float | None = None

    def update(self, sig: PhoneSignal) -> bool:
        self.last = sig
        speed = sig.speed_kmh or 0.0
        t = sig.wall_s

        if speed >= settings.PHONE_SPEED_ON_KMH:
            self._moving_since = self._moving_since if self._moving_since is not None else t
        else:
            self._moving_since = None
        if speed < settings.PHONE_SPEED_OFF_KMH and not sig.car_connected:
            self._still_since = self._still_since if self._still_since is not None else t
        else:
            self._still_since = None

        if not self.in_vehicle:
            if sig.car_connected or (
                self._moving_since is not None and t - self._moving_since >= settings.PHONE_ON_S
            ):
                self.in_vehicle = True
        elif self._still_since is not None and t - self._still_since >= settings.TRIP_END_S:
            # Stopped and disconnected long enough: trip over (traffic lights don't count).
            self.in_vehicle = False
        return self.in_vehicle

    def tick(self, wall_s: float) -> bool:
        """Called every engine tick. If the phone goes silent, hold the last state
        until TRIP_END_S has passed, then end the trip."""
        if self.in_vehicle and self.last is not None and wall_s - self.last.wall_s >= settings.TRIP_END_S:
            self.in_vehicle = False
        return self.in_vehicle

    def stale(self, wall_s: float) -> bool:
        return self.last is None or wall_s - self.last.wall_s >= settings.PHONE_STALE_S
