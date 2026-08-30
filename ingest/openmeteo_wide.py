#!/usr/bin/env python
"""
PRAVAAH A2-WIDE — NWP over a 1 deg lattice across NW India.

WHY THIS EXISTS (discovered 31 Aug 2026, the hard way)
------------------------------------------------------
RainFuse predicts the OFFICIAL IMD 24 h categories: 64.5 / 115.6 / 204.5 mm.
Inside the Delhi NCR box those categories are untrainable, because the box is
0.8 x 0.65 deg and IMD gridded is 0.25 deg -- SIX cells:

    heavy 64.5            37 positives
    very heavy 115.6       2 positives
    extremely heavy 204.5  0 positives      <- nothing to learn from

Widening to NW India (70-84E, 21-33N) on the SAME already-downloaded IMD files
gives 2,793 cells and turns that into:

    heavy 64.5         23,508
    very heavy 115.6    4,554
    extremely heavy       434

The charter always said "the rainfall layer runs nationwide" -- it is grid-based
and region-agnostic, unlike inundation which needs per-city terrain and labels.
So training the rain models on a wide domain is not a workaround; it is the
design, and it is what makes Proof P-4 (new region = one YAML) true rather than
aspirational.

Lattice is 1 deg here, not 0.1 deg: NWP precipitation fields are smooth at that
scale, 168 points is pullable in under an hour, and each IMD 0.25 deg cell joins
to its nearest NWP point.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd, requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "histfcst_wide"
ENDPOINT = "https://historical-forecast-api.open-meteo.com/v1/forecast"
START, END = "2021-01-01", "2025-09-30"
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
EXTRA = ["cape", "convective_inhibition", "lifted_index"]
W, E, S, N = 70.0, 84.0, 21.0, 33.0
STEP = 1.0


def lattice():
    lats = [round(S + i * STEP, 2) for i in range(int((N - S) / STEP) + 1)]
    lons = [round(W + j * STEP, 2) for j in range(int((E - W) / STEP) + 1)]
    return [(a, o) for a in lats for o in lons]


def _get(params, session, tries=6):
    delay = 5.0
    for _ in range(tries):
        try:
            r = session.get(ENDPOINT, params=params, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(delay); delay = min(delay * 2, 300); continue
            r.raise_for_status(); return r.json()
        except requests.RequestException:
            time.sleep(delay); delay = min(delay * 2, 300)
    raise RuntimeError("gave up")


def fetch(lat, lon, s):
    base = dict(latitude=lat, longitude=lon, start_date=START, end_date=END, timezone="UTC")
    a = _get({**base, "hourly": "precipitation", "models": ",".join(MODELS)}, s)
    df = pd.DataFrame(a["hourly"])
    b = _get({**base, "hourly": ",".join(EXTRA)}, s)
    df = df.merge(pd.DataFrame(b["hourly"]), on="time", how="outer")
    df["valid_time"] = pd.to_datetime(df["time"], utc=True)
    df = df.drop(columns=["time"]); df["lat"] = lat; df["lon"] = lon
    pc = [f"precipitation_{m}" for m in MODELS]
    for c in pc:
        if c not in df: df[c] = pd.NA
    df["nwp_spread"] = df[pc].max(axis=1) - df[pc].min(axis=1)
    df["nwp_mean"] = df[pc].mean(axis=1)
    df["nwp_n_models"] = df[pc].notna().sum(axis=1)
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pts = lattice()
    print(f"A2-WIDE: {len(pts)} points over NW India ({W}-{E}E, {S}-{N}N), {START}..{END}")
    ok = sk = 0
    with requests.Session() as s:
        for i, (lat, lon) in enumerate(pts, 1):
            p = OUT / f"w_{lat:.1f}_{lon:.1f}.parquet"
            if p.exists(): sk += 1; continue
            try:
                fetch(lat, lon, s).to_parquet(p, index=False); ok += 1
                print(f"[{i}/{len(pts)}] {lat},{lon} ok", flush=True)
            except Exception as e:
                print(f"[{i}/{len(pts)}] {lat},{lon} FAILED {e}", flush=True)
            time.sleep(2)
    print(f"done: {ok} fetched, {sk} present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
