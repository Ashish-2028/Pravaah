#!/usr/bin/env python
"""
PRAVAAH A2 — past NWP runs AS ISSUED, via Open-Meteo Historical Forecast
(BUILD_PLAN P3-T2). This is the leak-free NWP feature source.

WHAT THIS GIVES US THAT A1 CANNOT
---------------------------------
1. THREE INDEPENDENT PHYSICS MODELS in one call:
       precipitation_ecmwf_ifs025 / _gfs_seamless / _icon_seamless
   Their PAIRWISE DISAGREEMENT is itself a predictor of uncertainty — the
   single most defensible feature in RainFuse (PRAVAAH.md §7.2).

2. TRUE LEAD SEPARATION via `precipitation_previous_dayN` (probed and
   confirmed working 31 Aug 2026). `..._previous_day1` is what the model
   predicted for this timestamp when it ran a day earlier. That is a genuine
   ~24/48/72 h lead with a real implied issue_time — exactly the leak-free
   structure charter rule R4 demands, without us having to re-query per issue
   date.

3. CAPE / CONVECTIVE_INHIBITION / LIFTED_INDEX. These are ABSENT from the A1
   archive endpoint (it returns cape as 100% NULL — see PRAVAAH.md §5.6) but
   fully populated here. Instability is what separates "it will rain" from
   "it will pour", so this matters for the heavy-rain heads.

Two calls per lattice point:
   call A: models=3, hourly=precipitation            -> 3 model columns
   call B: previous_day1..3 + cape/cin/lifted_index  -> lead + instability

Coverage starts 2021 (the archive's own limit), which is why the NWP training
split is 2021-2023 while the observation split is 2018-2023.

    python ingest/openmeteo_histfcst.py --probe
    python ingest/openmeteo_histfcst.py
    python ingest/openmeteo_histfcst.py --status
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
OUT = ROOT / "data" / "raw" / "histfcst"

ENDPOINT = "https://historical-forecast-api.open-meteo.com/v1/forecast"

START = "2021-01-01"
END = "2025-09-30"

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
LEAD_VARS = [
    "precipitation_previous_day1",
    "precipitation_previous_day2",
    "precipitation_previous_day3",
]
INSTABILITY = ["cape", "convective_inhibition", "lifted_index"]


def lattice(cfg: dict) -> list[tuple[float, float]]:
    rl = cfg["rain_lattice"]
    res = rl["resolution_deg"]
    return [
        (round(rl["lat_start"] + i * res, 2), round(rl["lon_start"] + j * res, 2))
        for i in range(rl["lat_count"])
        for j in range(rl["lon_count"])
    ]


def _get(params: dict, session: requests.Session, tries: int = 6) -> dict:
    delay = 5.0
    for attempt in range(1, tries + 1):
        try:
            r = session.get(ENDPOINT, params=params, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                print(f"      HTTP {r.status_code}; backoff {delay:.0f}s "
                      f"({attempt}/{tries})", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 300)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            print(f"      {type(exc).__name__}; retry in {delay:.0f}s "
                  f"({attempt}/{tries})", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 300)
    raise RuntimeError("gave up after retries")


def fetch_point(lat: float, lon: float, session: requests.Session) -> pd.DataFrame:
    base = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START,
        "end_date": END,
        "timezone": "UTC",
    }

    a = _get({**base, "hourly": "precipitation", "models": ",".join(MODELS)}, session)
    df = pd.DataFrame(a["hourly"])

    b = _get({**base, "hourly": ",".join(LEAD_VARS + INSTABILITY)}, session)
    db = pd.DataFrame(b["hourly"])

    df = df.merge(db, on="time", how="outer")
    df["valid_time"] = pd.to_datetime(df["time"], utc=True)
    df = df.drop(columns=["time"])
    df["lat"] = lat
    df["lon"] = lon

    # ---- pairwise disagreement: the uncertainty signal, computed once here
    p = {m: f"precipitation_{m}" for m in MODELS}
    for c in p.values():
        if c not in df:
            df[c] = pd.NA
    df["nwp_spread"] = df[list(p.values())].max(axis=1) - df[list(p.values())].min(axis=1)
    df["nwp_mean"] = df[list(p.values())].mean(axis=1)
    df["d_ecmwf_gfs"] = (df[p["ecmwf_ifs025"]] - df[p["gfs_seamless"]]).abs()
    df["d_ecmwf_icon"] = (df[p["ecmwf_ifs025"]] - df[p["icon_seamless"]]).abs()
    df["d_gfs_icon"] = (df[p["gfs_seamless"]] - df[p["icon_seamless"]]).abs()

    # ---- issue_time. Charter R4: every forecast row carries BOTH stamps.
    # The base series is the archived short-lead forecast, so issue_time is the
    # same day; previous_dayN columns carry their own implied lead and are
    # named so the cube accessor can offset them explicitly.
    df["issue_time"] = df["valid_time"].dt.normalize()
    return df


def probe(cfg: dict) -> int:
    lat, lon = lattice(cfg)[24]
    print(f"PROBE lat={lat} lon={lon}  {START}..{END}")
    with requests.Session() as s:
        df = fetch_point(lat, lon, s)
    print(f"\nrows: {len(df):,}")
    print("columns:", list(df.columns))
    print("\nnull rate per column:")
    print((df.isna().mean() * 100).round(1).to_string())
    ev = df[(df.valid_time >= "2024-06-27") & (df.valid_time < "2024-06-29")]
    print("\n=== the demo event window, 3 models + leads ===")
    cols = [f"precipitation_{m}" for m in MODELS] + LEAD_VARS + ["cape", "nwp_spread"]
    print(ev.set_index("valid_time")[cols].round(1).to_string())
    return 0


def status(cfg: dict) -> int:
    pts = lattice(cfg)
    done = sorted(OUT.glob("hf_*.parquet"))
    print(f"{len(done)} / {len(pts)} points on disk")
    if done:
        print(f"total: {sum(p.stat().st_size for p in done)/1e6:.1f} MB")
        d = pd.read_parquet(done[0])
        print(f"sample rows={len(d):,} cols={len(d.columns)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0)
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text())
    if args.probe:
        return probe(cfg)
    if args.status:
        return status(cfg)

    OUT.mkdir(parents=True, exist_ok=True)
    pts = lattice(cfg)
    print(f"A2 NWP historical-forecast pull: {len(pts)} points, {START} -> {END}")
    print(f"  models: {MODELS}")
    print(f"  leads : {LEAD_VARS}")
    print(f"  instab: {INSTABILITY}")

    ok = skipped = 0
    t0 = time.time()
    with requests.Session() as session:
        for i, (lat, lon) in enumerate(pts, 1):
            path = OUT / f"hf_{lat:.2f}_{lon:.2f}.parquet"
            if path.exists():
                skipped += 1
                continue
            print(f"[{i:>2}/{len(pts)}] {lat:.2f},{lon:.2f} ...", end=" ", flush=True)
            try:
                df = fetch_point(lat, lon, session)
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED: {exc}", flush=True)
                continue
            df.to_parquet(path, index=False)
            ok += 1
            print(f"{len(df):,} rows -> {path.name}", flush=True)
            time.sleep(args.sleep)

    print(f"\ndone: {ok} fetched, {skipped} present, {len(pts)-ok-skipped} failed "
          f"({(time.time()-t0)/60:.1f} min)")
    return 0 if (ok + skipped) == len(pts) else 1


if __name__ == "__main__":
    sys.exit(main())
