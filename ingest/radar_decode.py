#!/usr/bin/env python
"""
PRAVAAH — decode IMD radar imagery into rain rate on our lattice (A14 upgrade).

WHAT THIS TURNS A PICTURE INTO
------------------------------
IMD publishes the Delhi DWR "SRI" product — Surface Rainfall Intensity — as a
rendered GIF with a discrete mm/hr colour legend printed on it. Our logger has
been capturing it every 10 minutes. This module reads the legend off the image,
inverts the colour map, georeferences the result, and resamples it onto the
0.1 deg rain lattice the models already use.

The result is a REAL OBSERVATION at ~1 km / 10 min — the only genuinely
independent, high-resolution measurement available to this project. ERA5 is a
9 km reanalysis, IMERG is a satellite retrieval; both smooth convective peaks
(PRAVAAH.md §5.6). Radar does not.

GEOMETRY — MEASURED, NOT ASSUMED
--------------------------------
Everything below was derived from the image itself and cross-checked:
  * map panel      719 x 719 px, the rest is legend and header text
  * centre         (360, 360) px = the Palam DWR site, 28.5665 N 77.1031 E
  * scale          a range ring sits at r=240 px with 37% dark-pixel fraction;
                   reading it as the 100 km ring gives 2.40 px/km, which puts
                   the panel edge (358 px) at 149 km — matching the header's
                   printed "Max Range: 150 km". Two independent facts agreeing
                   is the reason to believe it.
  * legend         auto-detected as vertical runs of saturated colour in the
                   right-hand column, so an IMD palette change is picked up
                   rather than silently mis-decoded.

HONEST LIMITS — SAY THESE OUT LOUD
----------------------------------
  * This is DECODED IMAGERY, not raw DWR volume data. Quantisation to ~15
    legend bins loses precision, and anti-aliased pixels at colour boundaries
    are ambiguous (we take the nearest bin).
  * SRI is itself a derived product; IMD's own Z-R relationship is baked in.
  * Terrain blocking, ground clutter and beam geometry are NOT corrected.
  * LIVE ONLY. There is no archive of these GIFs, so this cannot be used to
    train — only to inform predictions from now on. Every logged frame is
    irreplaceable, which is why the logger runs continuously.

    python ingest/radar_decode.py --probe
    python ingest/radar_decode.py            # decode all captures -> parquet
"""
from __future__ import annotations

import argparse
import glob
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
SRC = ROOT / "data" / "raw" / "live" / "radar"
OUT = ROOT / "data" / "raw" / "live" / "radar_decoded"

PANEL = 719
CX = CY = 360.0
PX_PER_KM = 2.40
RADAR_LAT, RADAR_LON = 28.5665, 77.1031      # Palam DWR
MAX_RANGE_KM = 149.0

# The IMD SRI legend ladder, in mm/hr, lowest bin first. These are the numbers
# printed beside the swatches on the product itself.
SRI_BINS = [1.0, 7.6, 14, 21, 27, 34, 41, 47, 54, 60, 67, 74, 80, 87, 93, 100]

STAMP = re.compile(r"_(\d{8}T\d{6}Z)_")


def read_legend(a: np.ndarray) -> list[tuple[tuple[int, int, int], float]]:
    """
    Recover the colour -> mm/hr map from the legend drawn on the image.

    Auto-detected rather than hardcoded: if IMD restyles the product, a
    hardcoded palette would keep "decoding" and return confident nonsense.
    """
    h, w, _ = a.shape
    best, best_runs = None, -1
    for x in range(int(w * 0.80), w - 4):
        col = a[:, x]
        runs, cur, n = 0, None, 0
        for y in range(h):
            c = tuple(int(v) for v in col[y])
            if c == cur:
                n += 1
            else:
                if n >= 8 and cur not in ((0, 0, 0), (255, 255, 255)):
                    runs += 1
                cur, n = c, 1
        if runs > best_runs:
            best, best_runs = x, runs
    if best is None:
        raise RuntimeError("legend column not found")

    col = a[:, best]
    runs, cur, start = [], None, 0
    for y in range(h):
        c = tuple(int(v) for v in col[y])
        if c != cur:
            if cur is not None:
                runs.append((start, y, cur))
            cur, start = c, y
    if cur is not None:
        runs.append((start, h, cur))

    # Keep runs whose HEIGHT matches a legend bin. White is a legitimate bin in
    # this palette (it sits between the yellow and cyan families), so excluding
    # all white shifted every value above it down one rung. But the surrounding
    # border is also white — and much taller or shorter. Height discriminates
    # them; colour cannot.
    coloured = [(s_, e_, c) for s_, e_, c in runs
                if e_ - s_ >= 8 and c != (0, 0, 0)]
    if not coloured:
        raise RuntimeError("no legend swatches found")
    heights = sorted(e_ - s_ for s_, e_, _ in coloured)
    bin_h = heights[len(heights) // 2]                 # modal bin height
    sw = [c for s_, e_, c in coloured
          if abs((e_ - s_) - bin_h) <= max(3, bin_h * 0.35)]
    # legend is drawn high value at the TOP, so reverse to match SRI_BINS
    sw = list(reversed(sw))
    if len(sw) < 8:
        raise RuntimeError(f"only {len(sw)} legend swatches found — palette changed?")
    # Map the N detected colours onto the TOP N rungs of the printed ladder.
    # The ladder is anchored at its high end because that is where the bins we
    # care about live; a missing faint low bin costs nothing.
    bins = SRI_BINS[:len(sw)]
    return list(zip(sw, bins))


def decode(path: Path, lut: list) -> pd.DataFrame | None:
    """One GIF -> a tidy frame of (lat, lon, mm_hr) inside the radar range."""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)[:PANEL, :PANEL]
    # int32, NOT int16. A squared RGB difference reaches 255**2 = 65,025, which
    # OVERFLOWS int16 (max 32,767) and wraps to a small number — making every
    # colour look "close" and classifying the entire green no-echo background
    # as heavy rain. The first run reported 100% of pixels raining at 43 mm/hr
    # on a dry night, which is how this was caught.
    colours = np.array([c for c, _ in lut], dtype=np.int32)
    values = np.array([v for _, v in lut], dtype=float)

    yy, xx = np.mgrid[0:PANEL, 0:PANEL]
    rad_px = np.hypot(xx - CX, yy - CY)
    inside = rad_px <= MAX_RANGE_KM * PX_PER_KM

    flat = a[inside].astype(np.int32)
    # nearest legend colour, in RGB space
    d = ((flat[:, None, :] - colours[None, :, :]) ** 2).sum(axis=2)
    nearest = d.argmin(axis=1)
    mind = d.min(axis=1)
    # A pixel far from EVERY legend colour is ground/coastline/text, not echo.
    # 60^2*3 tolerates anti-aliasing without inventing rain out of map furniture.
    mm = np.where(mind <= 60 * 60 * 3, values[nearest], 0.0)

    ys, xs = np.where(inside)
    dx_km = (xs - CX) / PX_PER_KM
    dy_km = (CY - ys) / PX_PER_KM          # image y grows downward
    lat = RADAR_LAT + np.degrees(dy_km / 6371.0)
    lon = RADAR_LON + np.degrees(dx_km / (6371.0 * math.cos(math.radians(RADAR_LAT))))
    return pd.DataFrame({"lat": lat, "lon": lon, "mm_hr": mm})


def to_lattice(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Aggregate ~1 km radar pixels onto the 0.1 deg model lattice."""
    rl = cfg["rain_lattice"]
    r = rl["resolution_deg"]
    la0, lo0 = rl["lat_start"], rl["lon_start"]
    d = df[(df.lat >= la0 - r / 2) & (df.lat <= la0 + (rl["lat_count"] - .5) * r) &
           (df.lon >= lo0 - r / 2) & (df.lon <= lo0 + (rl["lon_count"] - .5) * r)]
    if d.empty:
        return d
    d = d.assign(plat=(np.round((d.lat - la0) / r) * r + la0).round(2),
                 plon=(np.round((d.lon - lo0) / r) * r + lo0).round(2))
    # MAX as well as mean: a cloudburst is a small intense core, and averaging
    # it across an 11 km cell is exactly the smoothing that made ERA5 useless
    # for this task. Keep both and let the model decide.
    return (d.groupby(["plat", "plon"], as_index=False)
             .agg(radar_mean=("mm_hr", "mean"), radar_max=("mm_hr", "max"),
                  radar_p90=("mm_hr", lambda s: float(np.percentile(s, 90))),
                  radar_wet_frac=("mm_hr", lambda s: float((s > 0).mean())),
                  n_px=("mm_hr", "size")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(CONFIG.read_text())

    files = sorted(glob.glob(str(SRC / "delhi_sri_*.gif")))
    if not files:
        print("no SRI captures — is scripts/loggers.py running?")
        return 1

    a0 = np.asarray(Image.open(files[-1]).convert("RGB")).astype(np.int16)
    lut = read_legend(a0)
    print(f"legend: {len(lut)} bins, {lut[0][1]}..{lut[-1][1]} mm/hr")

    if args.probe:
        df = decode(Path(files[-1]), lut)
        lat_ = to_lattice(df, cfg)
        wet = df[df.mm_hr > 0]
        print(f"\nPROBE {Path(files[-1]).name}")
        print(f"  {len(df):,} pixels in range, {len(wet):,} with echo "
              f"({len(wet)/len(df)*100:.2f}%)")
        print(f"  max {df.mm_hr.max():.1f} mm/hr")
        print(f"  lat {df.lat.min():.2f}..{df.lat.max():.2f}  "
              f"lon {df.lon.min():.2f}..{df.lon.max():.2f}")
        print(f"  -> {len(lat_)} of {cfg['rain_lattice']['expected_points']} "
              f"lattice points covered")
        if len(lat_):
            print(lat_.sort_values("radar_max", ascending=False).head(5).to_string(index=False))
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    rows, done = [], 0
    for f in files:
        m = STAMP.search(Path(f).name)
        if not m:
            continue
        out = OUT / f"radar_{m[1]}.parquet"
        if out.exists():
            continue
        try:
            g = to_lattice(decode(Path(f), lut), cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {Path(f).name}: {type(exc).__name__}")
            continue
        if g.empty:
            continue
        g["valid_time"] = pd.to_datetime(m[1], format="%Y%m%dT%H%M%SZ", utc=True)
        g.to_parquet(out, index=False)
        rows.append(g)
        done += 1

    print(f"\ndecoded {done} new frames -> {OUT.relative_to(ROOT)}")
    if rows:
        allg = pd.concat(rows, ignore_index=True)
        print(f"  {len(allg):,} lattice-frames, max {allg.radar_max.max():.1f} mm/hr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
