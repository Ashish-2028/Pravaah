"""
PRAVAAH — grid definitions (BUILD_PLAN P3-T6).

Two grids, both derived from configs/aoi_delhi_ncr.yaml and NEVER hardcoded:

  RAIN LATTICE     0.1 deg, 56 points. The unit RainCast/RainFuse predict on.
  INUNDATION GRID  100 m, EPSG:32643. The unit InundaNet predicts on.

Anything that needs to know "where" imports from here, so a second region is
genuinely one YAML file (Proof P-4).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def bbox() -> tuple[float, float, float, float]:
    """(west, south, east, north) in EPSG:4326."""
    b = config()["bbox"]
    return b["west"], b["south"], b["east"], b["north"]


def rain_lattice() -> list[tuple[float, float]]:
    """The 56 (lat, lon) rain points, in a stable, reproducible order."""
    rl = config()["rain_lattice"]
    res = rl["resolution_deg"]
    pts = [
        (round(rl["lat_start"] + i * res, 2), round(rl["lon_start"] + j * res, 2))
        for i in range(rl["lat_count"])
        for j in range(rl["lon_count"])
    ]
    expected = rl["expected_points"]
    if len(pts) != expected:
        raise ValueError(f"lattice built {len(pts)} points, config expects {expected}")
    return pts


def nearest_lattice_point(lat: float, lon: float) -> tuple[float, float]:
    """Snap an arbitrary coordinate to its lattice cell — used to join wards to rain."""
    pts = np.array(rain_lattice())
    d = np.hypot(pts[:, 0] - lat, pts[:, 1] - lon)
    p = pts[int(d.argmin())]
    return float(p[0]), float(p[1])


def splits() -> dict:
    """TRAIN / VAL / TEST date ranges. Charter R5: by year and event, never random."""
    return config()["splits"]


def split_of(ts) -> str:
    """Which split a timestamp belongs to. Anything outside the ranges is 'none'."""
    import pandas as pd

    s = splits()
    y = pd.Timestamp(ts).year
    for name in ("val", "test"):
        lo, hi = s[name]
        if pd.Timestamp(lo).year <= y <= pd.Timestamp(hi).year:
            return name
    lo, hi = s["train"]["obs"]
    if pd.Timestamp(lo).year <= y <= pd.Timestamp(hi).year:
        return "train"
    return "none"


def thresholds() -> dict:
    return config()["thresholds"]


def events() -> list[dict]:
    return config()["events"]


def primary_event() -> dict:
    return next(e for e in events() if e.get("primary"))
