#!/usr/bin/env python
"""
PRAVAAH — quantile-map ERA5 onto the gauge-based IMD distribution.

THE PROBLEM, MEASURED
---------------------
ERA5-Land is a ~9 km reanalysis and it smooths convective extremes away. On
28 Jun 2024 — Safdarjung recorded 228 mm, the highest June day since 1936 —
ERA5 gave 20.9 mm near the station while IMD's gauge-interpolated grid gave
150.7 mm. ERA5 did not rank that day in the year's top eight.

RainCast trains on ERA5 as its answer key. So the model has, quite literally,
never been shown a cloudburst. Its 15 mm/h head had 63 test positives and had
to be dropped; the shipped heads are 5 and 10 mm/h, which are "heavy" only on
the ERA5 scale.

WHAT THIS DOES
--------------
Learns the monotone map that carries the ERA5 daily-rainfall distribution onto
the IMD daily distribution — classical quantile mapping / CDF matching, the
standard bias-correction method in climate and hydrology. Then RainCast can be
retrained against a target whose tail actually contains cloudbursts.

WHY IMD GRIDDED AND NOT STATION GAUGES
--------------------------------------
We do not have IMD station data — it is not free and the accounts are not
approved. IMD's 0.25 deg gridded product IS gauge-derived (interpolated from
their own station network) and it is free, so it is the best available anchor.
It is coarse: only 6 cells over the NCR box. That is why the map is fitted on
the WIDE domain (NW India, 2,793 cells x 7 monsoons), where there are enough
ERA5/IMD pairs to estimate a tail. Say the coarseness out loud rather than
implying we have station data.

NOAA ISD is used as an INDEPENDENT CHECK only, never as the anchor: it is
3-hourly synoptic with cumulative accumulation windows and heavy missingness,
which cannot support a distribution fit.

LEAKAGE
-------
The mapping is fitted on TRAIN YEARS ONLY and then applied to every year. A map
fitted on all years would fold test-year rainfall into the training target —
the same class of bug already caught twice in this project.

    python features/quantile_map.py --probe
    python features/quantile_map.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
CUBE = ROOT / "cube" / "ncr_cube.parquet"
IMD_WIDE = ROOT / "data" / "raw" / "imd_nw_daily.parquet"
ARCHIVE = ROOT / "data" / "raw" / "archive"
OUT = ROOT / "cube" / "quantile_map.json"

MONSOON = [6, 7, 8, 9]
TRAIN_MAX_YEAR = 2023          # matches the cube's obs train split
# Quantile grid: dense in the tail, because the tail is the entire point.
QS = np.concatenate([np.linspace(0.50, 0.98, 25),
                     np.linspace(0.982, 0.9995, 40)])


def load_pairs() -> tuple[np.ndarray, np.ndarray]:
    """
    Daily ERA5 and daily IMD over the WIDE domain, monsoon, train years.

    These are DISTRIBUTIONS, not paired samples: quantile mapping matches the
    shape of two populations, it does not require the same cell on the same
    day. That matters because ERA5 here is the NCR lattice while IMD is all of
    NW India — deliberately, since the NCR box holds only 6 IMD cells.
    """
    imd = pd.read_parquet(IMD_WIDE)
    imd["valid_time"] = pd.to_datetime(imd["valid_time"])
    imd = imd[imd.valid_time.dt.month.isin(MONSOON)
              & (imd.valid_time.dt.year <= TRAIN_MAX_YEAR)]
    y = imd["rain_mm"].to_numpy(dtype=float)

    files = sorted(ARCHIVE.glob("archive_*.parquet"))
    parts = []
    for f in files:
        d = pd.read_parquet(f, columns=["valid_time", "precipitation"]) \
            if "precipitation" in pd.read_parquet(f).columns else pd.read_parquet(f)
        col = "precipitation" if "precipitation" in d.columns else "precip_obs"
        d = d.rename(columns={col: "p"})
        d["valid_time"] = pd.to_datetime(d["valid_time"], utc=True)
        d = d[d.valid_time.dt.month.isin(MONSOON)
              & (d.valid_time.dt.year <= TRAIN_MAX_YEAR)]
        daily = d.set_index("valid_time")["p"].resample("D").sum()
        parts.append(daily)
    x = pd.concat(parts).to_numpy(dtype=float)
    return x, y


def fit(x: np.ndarray, y: np.ndarray) -> dict:
    """Monotone piecewise-linear map from ERA5 quantiles to IMD quantiles."""
    xs = np.quantile(x, QS)
    ys = np.quantile(y, QS)
    # Enforce monotonicity — sampling noise in the extreme tail can invert two
    # adjacent knots, and a non-monotone "correction" would reorder events.
    ys = np.maximum.accumulate(ys)
    xs = np.maximum.accumulate(xs)
    return {"q": QS.tolist(), "era5": xs.tolist(), "imd": ys.tolist(),
            "train_max_year": TRAIN_MAX_YEAR,
            "n_era5": int(x.size), "n_imd": int(y.size)}


def apply_map(v: np.ndarray, m: dict) -> np.ndarray:
    """
    Map ERA5 daily totals onto the IMD scale.

    Below the lowest knot the value passes through unchanged: the correction
    exists for the tail, and rescaling drizzle would add noise for nothing.
    Above the highest knot we extrapolate with the slope of the final segment
    rather than clipping, so an unprecedented ERA5 value is not silently capped
    at the training maximum.
    """
    xs = np.asarray(m["era5"], dtype=float)
    ys = np.asarray(m["imd"], dtype=float)
    v = np.asarray(v, dtype=float)
    out = np.interp(v, xs, ys)
    lo = v < xs[0]
    out[lo] = v[lo]
    hi = v > xs[-1]
    if hi.any() and len(xs) > 1:
        slope = (ys[-1] - ys[-2]) / max(xs[-1] - xs[-2], 1e-6)
        out[hi] = ys[-1] + (v[hi] - xs[-1]) * slope
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    x, y = load_pairs()
    print(f"ERA5 daily (NCR lattice, monsoon, <= {TRAIN_MAX_YEAR}): {x.size:,} values")
    print(f"IMD  daily (NW India,     monsoon, <= {TRAIN_MAX_YEAR}): {y.size:,} values")

    m = fit(x, y)
    print("\nquantile      ERA5 mm      IMD mm     ratio")
    for q in (0.50, 0.90, 0.99, 0.995, 0.999, 0.9995):
        i = int(np.argmin(np.abs(QS - q)))
        e, g = m["era5"][i], m["imd"][i]
        print(f"  {QS[i]:.4f}   {e:9.2f}   {g:9.2f}   {g/max(e,1e-6):7.2f}x")

    print(f"\nmax:  ERA5 {x.max():.1f} mm   IMD {y.max():.1f} mm")

    # What the demo event becomes
    ev = apply_map(np.array([20.9, 81.5]), m)
    print(f"\n28 Jun 2024 check (the reason this exists):")
    print(f"  ERA5 near Safdarjung  20.9 mm -> {ev[0]:6.1f} mm  (IMD grid said 150.7)")
    print(f"  ERA5 box max          81.5 mm -> {ev[1]:6.1f} mm  (station said 228)")

    if args.probe:
        return 0

    OUT.write_text(json.dumps(m, indent=1))
    print(f"\n  -> {OUT.relative_to(ROOT)}")
    print("  NOT yet applied to any training target — see the report before adopting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
