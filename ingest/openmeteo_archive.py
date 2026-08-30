#!/usr/bin/env python
"""
PRAVAAH A1 — ERA5-Land hourly archive via Open-Meteo (BUILD_PLAN P3-T1).

This is the TRAINING TARGET (the answer key) plus the observation features.
No API key. No quota account. This is the guaranteed spine of the whole cube —
if IMERG/GEE never lands, this alone still trains RainCast.

Design notes
------------
* RESUMABLE. One parquet per lattice point in data/raw/archive/. Re-running
  skips points already on disk, so a rate-limit or a laptop sleep costs
  nothing. (Charter R6 territory: never re-pull what you already have.)
* Pulls a continuous range so lag/antecedent features are computable across
  the monsoon boundary; monsoon filtering happens later, in the cube.
* Backs off politely on 429/5xx rather than hammering.
* --probe fetches ONE point and dumps the real response structure. Run this
  FIRST and read it before trusting the parser. (Charter rule R6.)

Usage
-----
    python ingest/openmeteo_archive.py --probe      # inspect one response
    python ingest/openmeteo_archive.py              # full 56-point pull
    python ingest/openmeteo_archive.py --status     # what's on disk
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
OUT = ROOT / "data" / "raw" / "archive"

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARS = [
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "surface_pressure",
    "soil_moisture_0_to_7cm",
]

# NOTE — 'cape' is NOT in this list, deliberately.
# Probed 31 Aug 2026: the archive endpoint returns cape as 100% NULL on every
# model (default / era5 / era5_seamless) — CAPE is an ERA5 single-levels field,
# not an ERA5-Land one. Requesting it here yields a silently useless all-null
# column, which is exactly the failure charter rule R6 exists to prevent.
#
# CAPE is sourced instead from A2 (historical-forecast-api), which serves it
# fully populated, along with convective_inhibition and lifted_index. That is
# architecturally better anyway: those rows carry a real issue_time, so the
# instability features obey the no-look-ahead law (R4) for free.
# See ingest/openmeteo_histfcst.py.

# Extend 15 days before the first monsoon so the 15-day antecedent index is
# defined on 1 June. End at the last monsoon date we train/test on.
START = "2018-05-15"
END = "2025-09-30"


def lattice(cfg: dict) -> list[tuple[float, float]]:
    rl = cfg["rain_lattice"]
    res = rl["resolution_deg"]
    pts = [
        (round(rl["lat_start"] + i * res, 2), round(rl["lon_start"] + j * res, 2))
        for i in range(rl["lat_count"])
        for j in range(rl["lon_count"])
    ]
    assert len(pts) == rl["expected_points"], f"expected {rl['expected_points']}, got {len(pts)}"
    return pts


def fetch(lat: float, lon: float, session: requests.Session, tries: int = 6) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START,
        "end_date": END,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "UTC",            # charter R8 — UTC internally, always
    }
    delay = 5.0
    for attempt in range(1, tries + 1):
        try:
            r = session.get(ENDPOINT, params=params, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                print(f"      HTTP {r.status_code}; backing off {delay:.0f}s "
                      f"(attempt {attempt}/{tries})", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 300)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            print(f"      {type(exc).__name__}: {exc}; retry in {delay:.0f}s "
                  f"({attempt}/{tries})", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 300)
    raise RuntimeError(f"gave up on ({lat}, {lon}) after {tries} attempts")


def to_frame(payload: dict, lat: float, lon: float) -> pd.DataFrame:
    h = payload["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["lat"] = lat
    df["lon"] = lon
    # valid_time == issue_time for observations: there is no forecast horizon
    # here. Keeping both columns means every table in the cube has the same
    # shape and cube.at(t0) needs no special case. (Charter R4.)
    df["valid_time"] = df["time"]
    df["issue_time"] = df["time"]
    return df.drop(columns=["time"])


def probe(cfg: dict) -> int:
    lat, lon = lattice(cfg)[0]
    print(f"PROBE  lat={lat} lon={lon}  {START}..{END}")
    with requests.Session() as s:
        payload = fetch(lat, lon, s)
    print("\ntop-level keys:", list(payload.keys()))
    for k in ("latitude", "longitude", "timezone", "elevation",
              "utc_offset_seconds", "generationtime_ms"):
        if k in payload:
            print(f"  {k}: {payload[k]}")
    print("\nhourly keys:", list(payload["hourly"].keys()))
    print("hourly_units:", payload.get("hourly_units"))
    n = len(payload["hourly"]["time"])
    print(f"\nrows: {n}  first={payload['hourly']['time'][0]}  "
          f"last={payload['hourly']['time'][-1]}")
    df = to_frame(payload, lat, lon)
    print("\ndtypes:\n", df.dtypes)
    print("\nhead:\n", df.head(3).to_string())
    print("\nnull counts:\n", df.isna().sum().to_string())
    print("\nprecipitation describe:\n", df["precipitation"].describe().to_string())
    return 0


def status(cfg: dict) -> int:
    pts = lattice(cfg)
    done = sorted(OUT.glob("archive_*.parquet"))
    print(f"{len(done)} / {len(pts)} points on disk")
    if done:
        total = sum(p.stat().st_size for p in done) / 1e6
        print(f"total size: {total:.1f} MB")
        df = pd.read_parquet(done[0])
        print(f"sample: {done[0].name}  rows={len(df)}  cols={list(df.columns)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="fetch one point, dump structure")
    ap.add_argument("--status", action="store_true", help="report progress")
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between points")
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text())
    if args.probe:
        return probe(cfg)
    if args.status:
        return status(cfg)

    OUT.mkdir(parents=True, exist_ok=True)
    pts = lattice(cfg)
    print(f"A1 ERA5-Land pull: {len(pts)} points, {START} -> {END}, "
          f"{len(HOURLY_VARS)} variables")

    ok = skipped = 0
    t0 = time.time()
    with requests.Session() as session:
        for i, (lat, lon) in enumerate(pts, 1):
            path = OUT / f"archive_{lat:.2f}_{lon:.2f}.parquet"
            if path.exists():
                skipped += 1
                continue
            print(f"[{i:>2}/{len(pts)}] {lat:.2f},{lon:.2f} ...", end=" ", flush=True)
            try:
                df = to_frame(fetch(lat, lon, session), lat, lon)
            except Exception as exc:  # noqa: BLE001 — keep going, resume later
                print(f"FAILED: {exc}", flush=True)
                continue
            df.to_parquet(path, index=False)
            ok += 1
            print(f"{len(df):,} rows -> {path.name}", flush=True)
            time.sleep(args.sleep)

    elapsed = time.time() - t0
    print(f"\ndone: {ok} fetched, {skipped} already present, "
          f"{len(pts) - ok - skipped} failed  ({elapsed/60:.1f} min)")
    print("re-run to retry failures (existing files are skipped)")
    return 0 if (ok + skipped) == len(pts) else 1


if __name__ == "__main__":
    sys.exit(main())
