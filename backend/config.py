"""Runtime configuration. All glucose thresholds are in mg/dL. Every field can be
overridden via an environment variable of the same name (e.g. ``SPEED=60``)."""
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    UNITS: Literal["mmol", "mgdl"] = "mmol"
    SPEED: float = 30.0
    TICK_S: float = 0.5

    # Alert thresholds (mg/dL, minutes)
    LOW: float = 70.0
    DRIVE_MIN: float = 90.0
    FAST_FALL: float = -2.0
    LOW_SOON_HORIZON: int = 30
    IMMINENT_HORIZON: int = 10

    # Alert behaviour (demo-clock minutes/seconds; the engine runs on demo time)
    RISE_MIN: float = 1.0  # mg/dL/min: "rising" after treatment (the ↗ arrow threshold)
    RECOVER_WAIT_MIN: float = 15.0  # RECOVERING countdown: wait, then recheck
    EPISODE_GAP_MIN: float = 10.0  # condition false this long → episode over, may speak again
    HYSTERESIS_READINGS: int = 2  # consecutive readings without the condition before dropping a level
    PRE_DRIVE_ESCALATE_S: float = 60.0  # PRE_DRIVE still true after this much driving → PULL_OVER
    REPEAT_PULL_OVER_MIN: float = 2.0  # unacknowledged PULL_OVER: repeat the audio once
    STALE_MIN: float = 15.0  # a reading older than this is "no data" (no new alerts from it)

    # Seat confirmation (glasses camera, during a <=3 min user-started session)
    EMA_ALPHA: float = 0.3
    ENTER_P: float = 0.70  # EMA above this → driver
    EXIT_P: float = 0.30  # EMA below this → passenger
    ENTER_S: float = 3.0  # EMA must hold past a threshold this long
    SESSION_MAX_S: float = 180.0  # platform limit on glasses sessions

    # In-vehicle detection (phone), wall-clock seconds
    PHONE_SPEED_ON_KMH: float = 15.0
    PHONE_ON_S: float = 10.0
    PHONE_SPEED_OFF_KMH: float = 5.0
    TRIP_END_S: float = 300.0  # stopped + disconnected (or phone silent) this long → trip over
    PHONE_STALE_S: float = 30.0

    SCENARIO: str = "falling_while_driving"
    SCENARIO_DIR: Path = ROOT / "data" / "scenarios"
    CITY_PATH: Path = ROOT / "data" / "city"
    WEB_DIR: Path = ROOT / "web"
    CLIP_MODEL: str = "ViT-B-32"
    CLIP_PRETRAINED: str = "laion2b_s34b_b79k"


settings = Settings()
