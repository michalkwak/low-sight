"""Alert engine. M1 stub: always NONE. The full state machine
(LOW_SOON / PULL_OVER / PRE_DRIVE / RECOVERING, dedupe, ack, escalation) lands
in M2 as a pure ``evaluate(prev_state, inputs, now) -> (alert, effects)``."""
from dataclasses import dataclass, field
from datetime import datetime

from backend.models import Alert, CGMReading, DrivingState, Forecast


@dataclass
class EngineInputs:
    reading: CGMReading | None
    trend: float | None
    forecast: Forecast | None
    driving: DrivingState


@dataclass
class EngineState:
    alert: Alert = field(default_factory=Alert)


def evaluate(prev: EngineState, inputs: EngineInputs, now: datetime) -> tuple[EngineState, list[dict]]:
    return EngineState(alert=Alert()), []
