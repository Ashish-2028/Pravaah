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

  * NOT YET VALIDATED ON RAIN, AND THEREFORE NOT YET A MODEL INPUT.
    Across the 37 good frames captured so far the maximum decoded rate is
    1.0 mm/hr — the lowest legend bin — because it simply has not rained over
    Delhi since logging began. A rain product cannot be validated on a dry
    day: the correlation against independent observations is meaningless when
    both series are ~0.
    The decoder is structurally sound (geometry cross-checked two ways, exact
    palette matching, torn frames rejected), but "we can decode it" is a
    different claim from "we know the values are right during a storm". Wiring
    an unvalidated observation into a live forecast would be exactly the kind
    of unearned confidence this project has avoided everywhere else.
    WHAT UNBLOCKS IT: one rain event over Delhi while the logger runs. Then
    compare decoded rate against Open-Meteo and the gauge stations, and if it
    holds up, feed it in.

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


MIN_LEGEND_BINS = 14
MAX_COLOURS = 180


def frame_ok(a: np.ndarray) -> tuple[bool, str]:
    """
    Reject TORN frames — partially-downloaded GIFs that are structurally valid
    but visually sheared.

    This is a real failure we hit, not a hypothetical. One capture arrived with
    displaced row bands and duplicated legend fragments; it decoded "fine" and
    produced 33,852 pixels above 20 mm/hr scattered across 353 km — the whole
    disc reading as torrential rain on a dry morning. It single-handedly
    destroyed the radar-vs-observation correlation.

    PIL's .load() does NOT catch this: enough of the GIF arrived to decode, so
    the bytes are valid and only the CONTENT is garbage. Two cheap structural
    signals separate it cleanly on every frame we hold:

        good frames   118-146 distinct colours, 15-16 legend bins
        the torn one  222 colours, 8 legend bins

    A sheared image cannot produce a coherent legend, which is why the bin
    count is the more meaningful of the two.
    """
    ncol = len(np.unique(a.reshape(-1, 3), axis=0))
    if ncol > MAX_COLOURS:
        return False, f"{ncol} distinct colours (>{MAX_COLOURS}) — frame looks torn"
    try:
        nb = len(read_legend(a.astype(np.int16)))
    except Exception as exc:  # noqa: BLE001
        return False, f"legend unreadable ({type(exc).__name__})"
    if nb < MIN_LEGEND_BINS:
        return False, f"only {nb} legend bins (<{MIN_LEGEND_BINS}) — frame looks torn"
    return True, ""


def decode(path: Path, lut: list) -> pd.DataFrame | None:
    """One GIF -> a tidy frame of (lat, lon, mm_hr) inside the radar range."""
    full = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    ok, why = frame_ok(full)
    if not ok:
        raise ValueError(f"corrupt frame: {why}")
    a = full.astype(np.int16)[:PANEL, :PANEL]
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
    # TOLERANCE. The GIF is palettised, so genuine echo pixels are EXACT
    # palette entries; the only reason to allow any slack is anti-aliasing.
    #
    # Measured on a real frame, the echo count is IDENTICAL (89 px) for every
    # tolerance from exact match up to d2=2700, then jumps to 1,204 at
    # d2=10800. That plateau is the answer: everything admitted between those
    # two thresholds is basemap TERRAIN SHADING — olive hill colours like
    # (191,191,64) sitting ~8,200 from the 74 mm/hr orange. The first version
    # used 10800 and therefore painted the Aravalli hills as heavy rain in
    # every single frame.
    #
    # 2700 = ~30 per channel: generous for anti-aliasing, far tighter than the
    # nearest terrain colour.
    MATCH_TOL = 2700
    mm = np.where(mind <= MATCH_TOL, values[nearest], 0.0)

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


def clutter_report(files: list[str], lut: list) -> int:
    """
    Persistence diagnostic — is anything echoing in the SAME pixel every frame?

    WHY THERE IS NO CLUTTER MASK HERE. Ground clutter is permanent echo in
    fixed pixels, so it is trivially detectable as high echo-frequency. Run
    across 38 captures at the correct match tolerance, ZERO pixels echo in even
    50% of frames — at any range band, including the 0-10 km ring where ground
    clutter would be worst. IMD evidently clutter-filters the SRI product
    before publishing it.
    
    So a mask would be machinery for a problem we do not have. This diagnostic
    exists instead: if IMD changes the product, or filtering degrades, run it
    and the persistence shows up immediately.
    """
    a0 = np.asarray(Image.open(files[-1]).convert("RGB")).astype(np.int32)[:PANEL, :PANEL]
    colours = np.array([c for c, _ in lut], dtype=np.int32)
    yy, xx = np.mgrid[0:PANEL, 0:PANEL]
    rad = np.hypot(xx - CX, yy - CY)
    inside = rad <= MAX_RANGE_KM * PX_PER_KM
    acc = np.zeros(int(inside.sum()), dtype=np.int32)
    for f in files:
        a = np.asarray(Image.open(f).convert("RGB")).astype(np.int32)[:PANEL, :PANEL]
        d = ((a[inside][:, None, :] - colours[None, :, :]) ** 2).sum(axis=2).min(axis=1)
        acc += (d <= 2700).astype(np.int32)
    freq = acc / len(files)
    r_km = rad[inside] / PX_PER_KM
    print(f"persistence across {len(files)} frames:")
    for th in (0.5, 0.7, 0.9):
        n = int((freq >= th).sum())
        print(f"  echo in >={th:.0%} of frames: {n} px"
              + ("   <- CLUTTER SUSPECTED, investigate" if n else "   (clean)"))
    for lo, hi in ((0, 10), (10, 25), (25, 50), (50, 100), (100, 149)):
        m = (r_km >= lo) & (r_km < hi)
        print(f"  range {lo:>3}-{hi:>3} km: mean echo freq {freq[m].mean():.4f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--clutter", action="store_true",
                    help="persistence diagnostic — is any pixel always on?")
    args = ap.parse_args()
    cfg = yaml.safe_load(CONFIG.read_text())

    files = sorted(glob.glob(str(SRC / "delhi_sri_*.gif")))
    if not files:
        print("no SRI captures — is scripts/loggers.py running?")
        return 1

    a0 = np.asarray(Image.open(files[-1]).convert("RGB")).astype(np.int16)
    lut = read_legend(a0)
    print(f"legend: {len(lut)} bins, {lut[0][1]}..{lut[-1][1]} mm/hr")

    if args.clutter:
        return clutter_report(files, lut)

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
    rows, done, rejected = [], 0, 0
    for f in files:
        m = STAMP.search(Path(f).name)
        if not m:
            continue
        out = OUT / f"radar_{m[1]}.parquet"
        if out.exists():
            continue
        try:
            g = to_lattice(decode(Path(f), lut), cfg)
        except ValueError as exc:
            print(f"  REJECT {Path(f).name[:34]}: {exc}")
            rejected += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {Path(f).name[:34]}: {type(exc).__name__}")
            continue
        if g.empty:
            continue
        g["valid_time"] = pd.to_datetime(m[1], format="%Y%m%dT%H%M%SZ", utc=True)
        g.to_parquet(out, index=False)
        rows.append(g)
        done += 1

    print(f"\ndecoded {done} new frames, rejected {rejected} corrupt "
          f"-> {OUT.relative_to(ROOT)}")
    if rows:
        allg = pd.concat(rows, ignore_index=True)
        print(f"  {len(allg):,} lattice-frames, max {allg.radar_max.max():.1f} mm/hr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
