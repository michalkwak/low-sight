"""Synthetic demo scenarios at 5-min resolution with mild sensor noise (±3 mg/dL).

Each scenario is a DataFrame with columns ``minute`` (offset from scenario start)
and ``mgdl``. Minutes start at ``-PREHISTORY_MIN`` so the forecaster already has
history at t=0; the ReplaySource maps minute 0 onto the demo clock's start time.
"""
import numpy as np
import pandas as pd

STEP_MIN = 5
PREHISTORY_MIN = 20


def _noise(n: int, rng: np.random.Generator, amp: float = 3.0) -> np.ndarray:
    return rng.uniform(-amp, amp, n)


def _build(name: str, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if name == "falling_while_driving":
        m = np.arange(-PREHISTORY_MIN, 121, STEP_MIN, dtype=float)
        # Slope (mg/dL/min) over the 5 min ending at each sample: 0 until 35,
        # then -1.0, -2.0, and -2.5 from 50. Crosses 70 at roughly 60-65 min.
        slope = np.select([m <= 35, m <= 40, m <= 45], [0.0, -1.0, -2.0], default=-2.5)
        v = 130 + np.concatenate([[0], np.cumsum(slope[1:] * STEP_MIN)])
        # Level off around 50 so the trace doesn't go absurd.
        v = np.maximum(v, 50)
    elif name == "low_before_drive":
        m = np.arange(-PREHISTORY_MIN, 91, STEP_MIN, dtype=float)
        v = 72 - 0.8 * m
        v = np.maximum(v, 55)
        # Treated at ~25 min: rise
        v = np.where(m > 25, 55 + 1.6 * (m - 25), v)
        v = np.minimum(v, 130)
    elif name == "stable_drive":
        m = np.arange(-PREHISTORY_MIN, 121, STEP_MIN, dtype=float)
        v = 125 + 12 * np.sin(m / 120 * 2 * np.pi)
    elif name == "treated_recovery":
        m = np.arange(-PREHISTORY_MIN, 121, STEP_MIN, dtype=float)
        down = np.minimum(110 - 1.5 * m, 130)  # falling to ~65 at 30 min
        up = 62 + 1.8 * (m - 35)  # treated at 35 min, rising
        v = np.where(m <= 35, down, up)
        v = np.clip(v, 60, 140)
    else:
        raise KeyError(f"unknown scenario {name!r}")
    v = v + _noise(len(v), rng)
    return pd.DataFrame({"minute": m.astype(int), "mgdl": np.round(v, 1)})


SCENARIOS = ["falling_while_driving", "low_before_drive", "stable_drive", "treated_recovery"]


def generate(name: str, seed: int = 7) -> pd.DataFrame:
    return _build(name, seed)


def generate_all(seed: int = 7) -> dict[str, pd.DataFrame]:
    return {n: generate(n, seed) for n in SCENARIOS}
