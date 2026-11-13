"""Loaders for scenario CSVs and (local-only) CITY trial exports.

CITY data must stay in data/city/ (gitignored) — use it for training/evaluation,
not for the public demo.
"""
from pathlib import Path

import pandas as pd


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a scenario CSV with columns ``minute,mgdl``."""
    df = pd.read_csv(path)
    missing = {"minute", "mgdl"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {missing}; found {list(df.columns)}")
    return df[["minute", "mgdl"]]


def load_city(path: str | Path, mapping: dict[str, str]) -> pd.DataFrame:
    """Load a CITY CGM export. ``mapping`` = {patient_col, time_col, value_col}.

    Returns columns ``patient, t, mgdl`` sorted by patient/time.
    """
    sep = "|" if str(path).endswith(".txt") else ","
    df = pd.read_csv(path, sep=sep)
    try:
        out = pd.DataFrame(
            {
                "patient": df[mapping["patient_col"]],
                "t": pd.to_datetime(df[mapping["time_col"]]),
                "mgdl": pd.to_numeric(df[mapping["value_col"]], errors="coerce"),
            }
        )
    except KeyError as e:
        print(f"[load_city] mapping failed ({e}). Columns in {path}:")
        for c in df.columns:
            print("   ", c)
        raise
    return out.dropna().sort_values(["patient", "t"]).reset_index(drop=True)


def find_lows(df: pd.DataFrame, below: float = 70, min_drop: float = 40, within_min: int = 60) -> pd.DataFrame:
    """Find falling episodes: a reading < ``below`` preceded within ``within_min``
    by a value at least ``min_drop`` higher. Returns patient, t_low, mgdl_low, peak."""
    rows = []
    for pid, g in df.groupby("patient"):
        g = g.set_index("t")["mgdl"]
        lows = g[g < below]
        last = None
        for t, v in lows.items():
            if last is not None and (t - last).total_seconds() < within_min * 60:
                continue
            window = g[t - pd.Timedelta(minutes=within_min) : t]
            if window.max() - v >= min_drop:
                rows.append({"patient": pid, "t_low": t, "mgdl_low": v, "peak": window.max()})
                last = t
    return pd.DataFrame(rows)
