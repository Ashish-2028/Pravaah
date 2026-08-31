#!/usr/bin/env python
"""
PRAVAAH A4 — GPM IMERG half-hourly satellite rainfall via Earth Engine.

WHY THIS IS THE BIGGEST AVAILABLE UPGRADE TO RAINCAST
-----------------------------------------------------
RainCast currently trains on ERA5-Land: a ~9 km REANALYSIS at HOURLY steps.
Two problems, both measured (PRAVAAH.md §5.6):
  * it smooths convective extremes (20.9 mm where the gauge read 228 mm), and
  * hourly steps are coarse for a 0-6 h nowcast.

IMERG is a SATELLITE OBSERVATION at 0.1 deg / 30 min. Two properties make it a
drop-in rather than a rebuild:
  1. 0.1 deg is EXACTLY our rain lattice resolution. No regridding, no
     interpolation, no new grid definition.
  2. Coverage is 2000-present, which fully contains our 2018-2025 window.

So it doubles the temporal resolution of the nowcast inputs and swaps a modelled
field for an observed one, on the grid we already use.

HONEST CAVEAT, STATED UP FRONT: IMERG is a satellite RETRIEVAL and it also
underestimates convective peaks — measured at 32.9 mm accumulated for the
28 Jun 2024 event vs 150.7 mm from IMD's gauge-based grid. It is better than
ERA5 for TIMING and STRUCTURE, not for absolute magnitude. It is a predictor,
not a truth source; IMD gridded stays the truth for exceedance.

NO DRIVE EXPORT NEEDED. The NCR box at 0.1 deg is 8 x 7 = 56 pixels, so a day of
half-hourly frames is only ~2,700 numbers. getRegion() returns that inline in one
call — far faster than a batch export, and it keeps us off the Community-tier
export queue entirely (charter D2: use GEE for extraction, never heavy compute).

    python ingest/imerg_gee.py --probe
    python ingest/imerg_gee.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
OUT = ROOT / "data" / "raw" / "imerg"

COLLECTION = "NASA/GPM_L3/IMERG_V07"
BAND = "precipitation"          # mm/hr rate on each half-hourly frame
SCALE = 11132                   # ~0.1 deg in metres, IMERG's native posting
MONSOON = [6, 7, 8, 9]
YEARS = range(2018, 2026)


def init_ee():
    import ee
    project = os.getenv("GEE_PROJECT")
    if not project:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("GEE_PROJECT="):
                    project = line.split("=", 1)[1].strip()
    if not project:
        raise RuntimeError("GEE_PROJECT not set (.env or environment)")
    ee.Initialize(project=project)
    return ee


def day_frame(ee, box, day: pd.Timestamp) -> pd.DataFrame:
    col = (ee.ImageCollection(COLLECTION)
             .filterDate(str(day.date()), str((day + pd.Timedelta(days=1)).date()))
             .select(BAND))
    rows = col.getRegion(box, SCALE).getInfo()
    if not rows or len(rows) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df.dropna(subset=[BAND])
    if df.empty:
        return df
    df["valid_time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.rename(columns={"longitude": "lon", "latitude": "lat",
                            BAND: "imerg_mm_hr"})
    return df[["lat", "lon", "valid_time", "imerg_mm_hr"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text())
    b = cfg["bbox"]
    ee = init_ee()
    box = ee.Geometry.Rectangle([b["west"], b["south"], b["east"], b["north"]])
    OUT.mkdir(parents=True, exist_ok=True)

    if args.probe:
        d = pd.Timestamp("2024-06-28")
        df = day_frame(ee, box, d)
        print(f"PROBE {d.date()}: {len(df):,} rows")
        print(f"  frames: {df.valid_time.nunique()}   cells: "
              f"{df.groupby(['lat','lon']).ngroups}")
        print(f"  peak rate: {df.imerg_mm_hr.max():.1f} mm/hr")
        print(f"  accumulated (rate*0.5h): {df.groupby(['lat','lon']).imerg_mm_hr.sum().max()*0.5:.1f} mm")
        print("\n", df.head(4).to_string())
        return 0

    days = [d for y in YEARS
            for d in pd.date_range(f"{y}-06-01", f"{y}-09-30", freq="D")
            if d.month in MONSOON and d <= pd.Timestamp("2025-09-30")]
    print(f"A4 IMERG: {len(days)} monsoon days, {YEARS.start}-{YEARS.stop-1}")

    ok = skip = fail = 0
    t0 = time.time()
    for i, d in enumerate(days, 1):
        path = OUT / f"imerg_{d.date()}.parquet"
        if path.exists():
            skip += 1
            continue
        try:
            df = day_frame(ee, box, d)
            if df.empty:
                fail += 1
                continue
            df.to_parquet(path, index=False)
            ok += 1
            if ok % 25 == 0:
                el = (time.time() - t0) / 60
                print(f"  [{i}/{len(days)}] {d.date()}  {ok} fetched  "
                      f"{el:.1f} min  eta {el/max(ok,1)*(len(days)-i):.0f} min",
                      flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            if fail % 20 == 1:
                print(f"  [{i}] {d.date()} FAILED {type(exc).__name__}: "
                      f"{str(exc)[:100]}", flush=True)
            time.sleep(2)
        time.sleep(args.sleep)

    print(f"\ndone: {ok} fetched, {skip} present, {fail} failed "
          f"({(time.time()-t0)/60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
