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

    # Driving-state smoothing
    EMA_ALPHA: float = 0.3
    ENTER_P: float = 0.70
    ENTER_S: float = 3.0
    EXIT_P: float = 0.30
    EXIT_S: float = 15.0

    SCENARIO: str = "falling_while_driving"
    SCENARIO_DIR: Path = ROOT / "data" / "scenarios"
    CITY_PATH: Path = ROOT / "data" / "city"
    WEB_DIR: Path = ROOT / "web"
    CLIP_MODEL: str = "ViT-B-32"
    CLIP_PRETRAINED: str = "laion2b_s34b_b79k"


settings = Settings()
