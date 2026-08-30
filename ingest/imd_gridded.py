#!/usr/bin/env python
"""
PRAVAAH A11 — IMD official gridded daily rainfall via imdlib (BUILD_PLAN P3-T4).

WHY THIS SOURCE WAS PROMOTED FROM "cross-check" TO "primary daily truth"
-----------------------------------------------------------------------
Probed 31 Aug 2026, on the flagship demo event (28 Jun 2024, the Delhi
cloudburst that collapsed the IGI terminal canopy; Safdarjung recorded
228 mm, the highest June daily total since 1936):

    source                              value at/near Safdarjung
    ---------------------------------   ------------------------
    Reality (IMD station, reported)     228   mm
    IMD gridded 0.25 deg (THIS FILE)    150.7 mm   <- ranks #1 wettest day of 2024
    ERA5-Land via Open-Meteo (A1)        20.9 mm   <- not even in the year's top 8

ERA5-Land is a ~9 km reanalysis. Reanalyses smooth convective extremes: the
timing is right (its peak lands at 22:00Z 27 Jun = 03:30 IST 28 Jun, matching
the reported cloudburst), but the magnitude is off by an order of magnitude and
the maximum is misplaced to the SE corner of the box.

CONSEQUENCES — these are load-bearing decisions, not trivia:
  1. ERA5 must NOT be the sole training target for heavy-rain exceedance.
     A model trained only on ERA5 learns to predict smoothed rain and can
     never predict a cloudburst, because its answer key never contains one.
  2. IMD gridded becomes the truth layer for the DAILY exceedance heads
     (RainFuse: 64.5 / 115.6 / 204.5 mm). Those are IMD's OWN official
     categories, so verifying them against IMD's OWN observational product is
     the most defensible choice available to us in front of IMD judges.
  3. ERA5 keeps its job: hourly structure — lags, accumulations, antecedent
     indices, and the sub-daily dynamics RainCast needs. IMD gridded is daily
     only, so it cannot do that job.
  4. This disagreement is not an embarrassment, it is EVIDENCE FOR PROOF P-1
     (fusion). Two truth sources disagree in a measurable, explainable way;
     that is precisely the argument for fusing source families rather than
     trusting one. Quantified, it belongs on the honesty slide.

Access: no key, no account. `pip install imdlib`, data from imdpune.gov.in.
Coverage: 0.25 deg, 1901-2024. NOTE 2025 is typically not yet published, so
the TEST split (2025) must fall back to ERA5 + IMERG.

    python ingest/imd_gridded.py --probe          # one year, inspect
    python ingest/imd_gridded.py                  # full pull
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
RAW = ROOT / "data" / "raw" / "imd"
OUT = ROOT / "data" / "raw" / "imd_ncr_daily.parquet"

# imdlib encodes missing data as a large sentinel (-999 / 99.9-style values
# depending on product). Anything above this is not rainfall.
NODATA_ABOVE = 3000.0

FIRST_YEAR = 2018
LAST_YEAR = 2024          # 2025 not published; TEST split uses ERA5/IMERG


def _box(cfg: dict) -> dict:
    return cfg["bbox"]


def fetch_years(y0: int, y1: int, cfg: dict) -> pd.DataFrame:
    import imdlib as imd

    RAW.mkdir(parents=True, exist_ok=True)
    b = _box(cfg)
    frames = []
    for year in range(y0, y1 + 1):
        print(f"  {year} ...", end=" ", flush=True)
        try:
            ds = imd.get_data("rain", year, year, fn_format="yearwise",
                              file_dir=str(RAW)).get_xarray()
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED: {type(exc).__name__}: {exc}")
            continue
        r = ds["rain"].sel(lat=slice(b["south"], b["north"]),
                           lon=slice(b["west"], b["east"]))
        r = r.where(r < NODATA_ABOVE)
        df = r.to_dataframe(name="rain_mm").reset_index().dropna(subset=["rain_mm"])
        frames.append(df)
        print(f"{len(df):,} cell-days, box max {df['rain_mm'].max():.1f} mm")

    if not frames:
        raise RuntimeError("no years fetched")
    out = pd.concat(frames, ignore_index=True)
    out["time"] = pd.to_datetime(out["time"])
    out = out.rename(columns={"time": "valid_time"})
    # Daily observation: issue_time == valid_time, same convention as A1, so
    # cube.at(t0) needs no special case (charter R4).
    out["issue_time"] = out["valid_time"]
    out["source"] = "imd_gridded_0.25deg"
    return out


def probe(cfg: dict) -> int:
    df = fetch_years(2024, 2024, cfg)
    print("\ncolumns:", list(df.columns))
    print("dtypes:\n", df.dtypes.to_string())
    print(f"\nrows: {len(df):,}  cells: {df.groupby(['lat','lon']).ngroups}")
    print("\n=== top 8 wettest NCR days, 2024 (IMD official) ===")
    top = df.groupby("valid_time")["rain_mm"].max().sort_values(ascending=False).head(8)
    print(top.round(1).to_string())
    print("\n=== 28 Jun 2024 (the demo event) ===")
    ev = df[df["valid_time"] == "2024-06-28"]
    print(f"box max {ev['rain_mm'].max():.1f} mm   box mean {ev['rain_mm'].mean():.1f} mm")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--start", type=int, default=FIRST_YEAR)
    ap.add_argument("--end", type=int, default=LAST_YEAR)
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text())
    if args.probe:
        return probe(cfg)

    print(f"A11 IMD gridded daily rainfall, {args.start}-{args.end}, NCR box")
    df = fetch_years(args.start, args.end, cfg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(df):,} rows)")
    print("\n=== extreme-day catalogue: top 12 NCR days in record ===")
    top = df.groupby("valid_time")["rain_mm"].max().sort_values(ascending=False).head(12)
    print(top.round(1).to_string())
    print("\nThese are candidate training events and candidate demo events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
