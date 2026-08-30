#!/usr/bin/env python
"""
PRAVAAH — assemble the fusion cube (BUILD_PLAN P3-T7).

WHAT THE CUBE IS
----------------
One tidy table. Each row is ONE PLACE at ONE HOUR. The columns are everything
every source knows about that place-hour. One column is the answer.

"Fusion" is not a metaphor here: it literally means all source families sit in
the same row, so a model can learn which columns to trust under which
conditions — and the ablation table (Proof P-1) proves it did.

WHAT GOES IN
------------
  A1  ERA5-Land hourly obs      2018-05-15 .. 2025-09-30   56 pts   (the spine)
  A2  NWP as-issued, 3 models   2021-03-23 .. 2025-09-30   56 pts
  A11 IMD official gridded      2018 .. 2024, DAILY        (the extreme truth)

THE TRUTH-SOURCE PROBLEM, MADE EXPLICIT
---------------------------------------
Measured on 28 Jun 2024 (Safdarjung station recorded 228 mm):

    gauge-based   IMD gridded 0.25 deg   150.7 mm   <- captures the extreme
    satellite     IMERG 0.1 deg           32.9 mm   <- retrieval underestimates convection
    reanalysis    ERA5-Land ~9 km         20.9 mm   <- most smoothed of all

Note this is NOT a resolution ranking — IMERG is FINER than IMD gridded and
still lower. It is a MEASUREMENT-TYPE ranking. Each family has a characteristic
bias, which is exactly why fusing them beats trusting any one.

So the cube carries BOTH truths and names them honestly:
    precip_obs      hourly ERA5   -> RainCast's sub-daily structure/dynamics
    imd_rain_daily  daily IMD     -> the heavy-rain exceedance truth

NWP AVAILABILITY IS NOT UNIFORM — probed, not assumed:
    gfs_seamless   from 2021-03-23   (78% of 2021, 100% from 2023)
    icon_seamless  from 2022-11-16   (100% from 2023)
    ecmwf_ifs025   from 2024-02-02   (100% in 2025)
    previous_dayN  from 2024-01-19
Consequence: 3-model disagreement only exists from 2024. LightGBM handles NaN
natively, so columns are kept as NaN rather than imputed, and `nwp_n_models`
records how many were actually available in that row — a model can then learn
"trust the spread only when the spread is real".

    python cube/build_cube.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cube.grid import rain_lattice, split_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "raw" / "archive"
HISTFCST = ROOT / "data" / "raw" / "histfcst"
IMD = ROOT / "data" / "raw" / "imd_ncr_daily.parquet"
OUT = ROOT / "cube" / "ncr_cube.parquet"

NWP_COLS = [
    "precipitation_ecmwf_ifs025",
    "precipitation_gfs_seamless",
    "precipitation_icon_seamless",
]


def load_obs() -> pd.DataFrame:
    files = sorted(ARCHIVE.glob("archive_*.parquet"))
    if not files:
        raise FileNotFoundError("no A1 files — run ingest/openmeteo_archive.py")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df = df.rename(columns={
        "precipitation": "precip_obs",
        "temperature_2m": "temp",
        "relative_humidity_2m": "rh",
        "wind_speed_10m": "wind",
        "surface_pressure": "pres",
        "soil_moisture_0_to_7cm": "soil_moist",
    })
    print(f"  A1 obs      {len(df):>10,} rows  {df.valid_time.min()} .. {df.valid_time.max()}")
    return df


def load_nwp() -> pd.DataFrame:
    files = sorted(HISTFCST.glob("hf_*.parquet"))
    if not files:
        print("  A2 nwp      MISSING — cube will have no NWP columns")
        return pd.DataFrame()
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    # How many physics models actually spoke in this row? Lets the model learn
    # to trust `nwp_spread` only when the spread is computed from >1 model.
    df["nwp_n_models"] = df[NWP_COLS].notna().sum(axis=1)
    df = df.drop(columns=["issue_time"])   # obs issue_time is authoritative below
    print(f"  A2 nwp      {len(df):>10,} rows  {df.valid_time.min()} .. {df.valid_time.max()}")
    return df


def load_imd() -> pd.DataFrame:
    if not IMD.exists():
        print("  A11 imd     MISSING — no gauge-based daily truth")
        return pd.DataFrame()
    df = pd.read_parquet(IMD)
    # DIRECTION MATTERS. IMD is COARSER (0.25 deg) than the lattice (0.1 deg),
    # so we must map EVERY LATTICE POINT to its nearest IMD cell — not every
    # IMD cell to its nearest lattice point. Doing it the wrong way round
    # leaves most lattice points unmatched (it produced 9.6% coverage instead
    # of ~100% for 2018-2024). Coarse-to-fine means several lattice points
    # legitimately share one IMD value; that is the resolution being honest,
    # not a bug.
    imd_cells = df[["lat", "lon"]].drop_duplicates().to_numpy()
    rows = []
    for lat, lon in rain_lattice():
        d = ((imd_cells[:, 0] - lat) ** 2 + (imd_cells[:, 1] - lon) ** 2)
        c = imd_cells[int(d.argmin())]
        rows.append({"lat": lat, "lon": lon,
                     "imd_lat": float(c[0]), "imd_lon": float(c[1])})
    xwalk = pd.DataFrame(rows)
    print(f"  A11 imd     {len(imd_cells)} IMD cells -> {len(xwalk)} lattice points")

    daily = df.rename(columns={"lat": "imd_lat", "lon": "imd_lon",
                               "rain_mm": "imd_rain_daily"})
    daily = daily.merge(xwalk, on=["imd_lat", "imd_lon"], how="inner")
    daily["date"] = pd.to_datetime(daily["valid_time"]).dt.tz_localize("UTC").dt.normalize()
    daily = daily[["lat", "lon", "date", "imd_rain_daily"]].drop_duplicates(
        subset=["lat", "lon", "date"])
    print(f"  A11 imd     {len(daily):>10,} lattice-days after crosswalk")
    return daily


def main() -> int:
    print("Building the fusion cube")
    obs = load_obs()
    nwp = load_nwp()
    imd = load_imd()

    cube = obs
    if not nwp.empty:
        cube = cube.merge(nwp, on=["lat", "lon", "valid_time"], how="left")
    if not imd.empty:
        cube["date"] = cube["valid_time"].dt.normalize()
        cube = cube.merge(imd, on=["lat", "lon", "date"], how="left")

    # ---- THE LAW (charter R4), and it needs TWO stamps, not one.
    #
    # For OBSERVATIONS, issue_time == valid_time: an observation of 04:00 exists
    # at 04:00 and not before. That is correct but trivially true, and if it were
    # the only stamp in the cube the accessor would be filtering on nothing —
    # eval/leakage_tests.py caught exactly that and failed the build.
    #
    # FORECASTS are different: a value VALID at 04:00 may have been ISSUED long
    # after 04:00, and using it at 04:00 is reading tomorrow's newspaper. So NWP
    # columns get their own stamp.
    #
    # nwp_issue_time is deliberately CONSERVATIVE: the 00Z run of a global model
    # is not on the wire at 00Z — it takes hours to run and publish, typically
    # available ~05-06Z. We assume 06:00 UTC. Being conservative can only ever
    # cost us skill; being optimistic would silently manufacture it.
    cube["issue_time"] = cube["issue_time"].fillna(cube["valid_time"])
    cube["nwp_issue_time"] = cube["valid_time"].dt.normalize() + pd.Timedelta(hours=6)

    # The previous_dayN columns are genuinely issued N days earlier — that is
    # what makes them true leak-free multi-lead features (see A2 docstring).
    for n in (1, 2, 3):
        cube[f"nwp_issue_time_prev{n}"] = (
            cube["valid_time"].dt.normalize() - pd.Timedelta(days=n) + pd.Timedelta(hours=6)
        )

    cube["split"] = cube["valid_time"].map(split_of)

    cube = cube.sort_values(["lat", "lon", "valid_time"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cube.to_parquet(OUT, index=False)

    print(f"\n  -> {OUT.relative_to(ROOT)}")
    print(f"  rows {len(cube):,}   cols {len(cube.columns)}   "
          f"{OUT.stat().st_size/1e6:.1f} MB")
    print(f"  points {cube.groupby(['lat','lon']).ngroups}")
    print("\n  split sizes:")
    print(cube["split"].value_counts().to_string())
    print("\n  column availability (% non-null):")
    print((cube.notna().mean() * 100).round(1).to_string())

    # ---- CHECKPOINT: the demo event must be visible in the spine
    ev = cube[(cube.valid_time >= "2024-06-27T12:00Z")
              & (cube.valid_time < "2024-06-28T12:00Z")]
    print(f"\n  CHECKPOINT 28 Jun 2024 window: {len(ev):,} rows, "
          f"ERA5 box max {ev.precip_obs.max():.1f} mm/h", end="")
    if "imd_rain_daily" in ev:
        print(f", IMD daily box max {ev.imd_rain_daily.max():.1f} mm")
    else:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
