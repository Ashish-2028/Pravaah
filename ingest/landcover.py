#!/usr/bin/env python
"""
PRAVAAH A5 / P2-T8 — impervious + built-up ingest, WITHOUT Google Earth Engine.

Two independent sources, both public, both direct-download, no account:

  1. ESA WorldCover 10 m v200 (2021)  — s3://esa-worldcover, UNSIGNED.
     Class 50 = Built-up.  This is a CLASSIFICATION: every 10 m pixel is
     built-up or it is not, so the fraction of class-50 pixels inside a 100 m
     cell is a real, countable impervious fraction.
  2. GHSL GHS-BUILT-S R2023A, epoch 2020, 100 m, Mollweide — JRC direct tile
     download.  This is a REGRESSION: each 100 m cell carries built-up
     SURFACE in m^2 (0..10000).  Different sensors, different method, different
     year — a genuine second opinion on the same quantity, which is the only
     reason to carry both.

Charter rules honoured
----------------------
R6  Nothing is hardcoded from memory. The WorldCover tile names are DERIVED
    from the AOI bbox and then CHECKED against a live listing of the bucket
    before anything is downloaded; the GHSL tile is derived by projecting the
    bbox into Mollweide and indexing the published global tile grid, then
    verified against the downloaded tile's own bounds.
R7  Every coordinate comes from configs/aoi_delhi_ncr.yaml. Swap the YAML,
    get a new region — including a different set of tiles.
R3  Prints the real class histogram over the AOI. A silently-empty or
    wrongly-decoded read shows up here as an impossible landcover mix.

Outputs (both cached; re-running is a no-op)
--------------------------------------------
    data/raw/landcover/worldcover_aoi.tif   uint8 classes, EPSG:4326, 10 m
    data/raw/landcover/ghsl_built_s_aoi.tif float32 m^2/cell, ESRI:54009, 100 m

Usage
-----
    python ingest/landcover.py             # cached
    python ingest/landcover.py --force
    python ingest/landcover.py --no-ghsl   # WorldCover only
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
RAW = ROOT / "data" / "raw" / "landcover"

# Halo around the AOI, in degrees. The 100 m UTM grid is snapped OUTWARD from
# the projected bbox, so it pokes past the lat/lon bbox by up to a cell plus
# the curvature of the UTM graticule. Same value as ingest/dem.py.
PAD_DEG = 0.05

# ---- ESA WorldCover, AWS Open Data -----------------------------------------
WC_BUCKET = "esa-worldcover"
WC_PREFIX = "v200/2021/map/"
WC_TILE_DEG = 3          # published "3x3 degree tiling grid" (product tag)
# The class legend is carried in the tile's own GDAL metadata; we assert
# against it at read time rather than trusting this constant.
WC_BUILT_UP = 50

# ---- GHSL GHS-BUILT-S R2023A, JRC ------------------------------------------
GHSL_BASE = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
             "GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/"
             "V1-0/tiles/")
GHSL_STEM = "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0"
GHSL_CRS = "ESRI:54009"
# Published R2023A global tile grid: 36 columns x 18 rows over the full
# Mollweide envelope. Verified below against the tile's own bounds.
GHSL_X0, GHSL_Y0 = -18041000.0, 9020000.0
GHSL_NCOL, GHSL_NROW = 36, 18
GHSL_CELL_M2 = 100.0 * 100.0     # denominator for surface -> fraction


def load_cfg() -> dict:
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


def padded_bbox(cfg: dict) -> tuple[float, float, float, float]:
    b = cfg["bbox"]
    return (b["west"] - PAD_DEG, b["south"] - PAD_DEG,
            b["east"] + PAD_DEG, b["north"] + PAD_DEG)


# ============================================================ ESA WorldCover

def worldcover_tiles(w: float, s: float, e: float, n: float) -> list[str]:
    """Which 3x3 degree tiles does this bbox touch? Derived, not remembered."""
    d = WC_TILE_DEG
    lats = range(int(np.floor(s / d)) * d, int(np.floor(n / d)) * d + 1, d)
    lons = range(int(np.floor(w / d)) * d, int(np.floor(e / d)) * d + 1, d)
    out = []
    for la in lats:
        for lo in lons:
            out.append(f"{'N' if la >= 0 else 'S'}{abs(la):02d}"
                       f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}")
    return out


def worldcover_keys(tiles: list[str]) -> dict[str, str]:
    """R6 — LIST the bucket and match real keys. Never assume a path."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    found = {}
    for t in tiles:
        pfx = f"{WC_PREFIX}ESA_WorldCover_10m_2021_v200_{t}_"
        r = s3.list_objects_v2(Bucket=WC_BUCKET, Prefix=pfx)
        keys = [o["Key"] for o in r.get("Contents", [])
                if o["Key"].endswith("_Map.tif")]
        if not keys:
            print(f"  !! no _Map.tif under s3://{WC_BUCKET}/{pfx}")
            continue
        sz = {o["Key"]: o["Size"] for o in r["Contents"]}
        print(f"  listed   {t} -> {Path(keys[0]).name}  "
              f"({sz[keys[0]]/1e6:.0f} MB)")
        found[t] = keys[0]
    if not found:
        sys.exit(f"no WorldCover tiles found for {tiles} — bucket layout "
                 f"changed; inspect s3://{WC_BUCKET}/{WC_PREFIX}")
    return found


def fetch_worldcover(cfg: dict, force: bool) -> Path:
    out = RAW / "worldcover_aoi.tif"
    if out.exists() and not force:
        print(f"  cached   {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
        return out

    w, s, e, n = padded_bbox(cfg)
    tiles = worldcover_tiles(w, s, e, n)
    print(f"  bbox +{PAD_DEG} deg -> tiles {tiles}")
    keys = worldcover_keys(tiles)

    # The tiles are Cloud-Optimised GeoTIFFs, so a windowed read over
    # /vsis3/ transfers only the blocks the AOI actually touches: ~10 MB
    # instead of the ~91 MB tile. GDAL_DISABLE_READDIR_ON_OPEN stops it
    # probing for sidecars that are not there.
    import os
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

    pieces = []
    legend = None
    for t, key in keys.items():
        url = f"/vsis3/{WC_BUCKET}/{key}"
        with rasterio.open(url) as src:
            legend = src.tags().get("legend", legend)
            bw, bs, be, bn = src.bounds
            # clip the request to this tile's own footprint
            cw, cs, ce, cn = max(w, bw), max(s, bs), min(e, be), min(n, bn)
            if cw >= ce or cs >= cn:
                print(f"  skip     {t}: does not actually intersect the AOI")
                continue
            win = from_bounds(cw, cs, ce, cn, src.transform).round_offsets() \
                                                            .round_lengths()
            arr = src.read(1, window=win)
            tr = src.window_transform(win)
            print(f"  read     {t} window {arr.shape} from {url}")
            pieces.append((arr, tr, src.crs))

    assert pieces, "every candidate tile was skipped — check the bbox"
    if len(pieces) == 1:
        arr, tr, crs = pieces[0]
    else:
        from rasterio.merge import merge as rio_merge
        from rasterio.io import MemoryFile
        mems, opened = [], []
        for a, t_, c in pieces:
            mf = MemoryFile()
            with mf.open(driver="GTiff", height=a.shape[0], width=a.shape[1],
                         count=1, dtype="uint8", crs=c, transform=t_,
                         nodata=0) as d:
                d.write(a, 1)
            mems.append(mf)
            opened.append(mf.open())
        merged, tr = rio_merge(opened)
        arr, crs = merged[0], opened[0].crs
        for o in opened:
            o.close()

    assert legend and f"{WC_BUILT_UP}" in legend, "legend tag missing"
    built_line = [ln for ln in legend.splitlines()
                  if ln.strip().startswith(str(WC_BUILT_UP))]
    assert built_line and "Built-up" in built_line[0], (
        f"class {WC_BUILT_UP} is not 'Built-up' in this product's legend:\n"
        f"{legend}")
    print(f"  legend confirms class {WC_BUILT_UP} = "
          f"{built_line[0].split(None, 1)[1].strip()}")

    RAW.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=arr.shape[0],
                       width=arr.shape[1], count=1, dtype="uint8",
                       crs=crs, transform=tr, nodata=0,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr, 1)
        dst.update_tags(legend=legend, source="ESA WorldCover 10m 2021 v200",
                        s3=f"s3://{WC_BUCKET}/{WC_PREFIX}")
    describe_worldcover(arr, legend)
    print(f"  wrote {out}  ({out.stat().st_size/1e6:.1f} MB)  {arr.shape}")
    return out


def describe_worldcover(arr: np.ndarray, legend: str) -> None:
    names = {}
    for ln in legend.splitlines():
        p = ln.split(None, 1)
        if len(p) == 2 and p[0].isdigit():
            names[int(p[0])] = p[1].strip()
    vals, cnt = np.unique(arr, return_counts=True)
    tot = arr.size
    print(f"  class histogram over the AOI window ({tot:,} 10 m pixels):")
    for v, c in sorted(zip(vals, cnt), key=lambda kv: -kv[1]):
        print(f"    {int(v):>4}  {names.get(int(v), 'NODATA'):<26} "
              f"{c:>12,}  {100*c/tot:>6.2f} %")
    nod = int(cnt[vals == 0].sum()) if 0 in vals else 0
    if nod:
        print(f"  !! {100*nod/tot:.3f} % nodata inside the AOI window")


# ============================================================ GHSL

def ghsl_tile(cfg: dict) -> str:
    """Index the published R2023A Mollweide tile grid from the AOI bbox."""
    from pyproj import Transformer

    tf = Transformer.from_crs(cfg["crs"]["geographic"], GHSL_CRS,
                              always_xy=True)
    w, s, e, n = padded_bbox(cfg)
    tw = (2 * abs(GHSL_X0)) / GHSL_NCOL
    th = (2 * abs(GHSL_Y0)) / GHSL_NROW
    seen = set()
    for lon in (w, e):
        for lat in (s, n):
            x, y = tf.transform(lon, lat)
            seen.add((int((GHSL_Y0 - y) // th) + 1,
                      int((x - GHSL_X0) // tw) + 1))
    if len(seen) > 1:
        print(f"  !! AOI spans {len(seen)} GHSL tiles {sorted(seen)}; "
              f"only the first is fetched — extend fetch_ghsl() for a "
              f"larger region")
    r, c = sorted(seen)[0]
    return f"R{r}_C{c}"


def fetch_ghsl(cfg: dict, force: bool) -> Path | None:
    out = RAW / "ghsl_built_s_aoi.tif"
    if out.exists() and not force:
        print(f"  cached   {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
        return out

    import urllib.request

    from pyproj import Transformer

    tile = ghsl_tile(cfg)
    url = f"{GHSL_BASE}{GHSL_STEM}_{tile}.zip"
    print(f"  tile {tile} -> {url}")
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            blob = r.read()
    except Exception as exc:                       # noqa: BLE001
        print(f"  !! GHSL download failed ({exc}); continuing without it")
        return None
    print(f"  downloaded {len(blob)/1e6:.1f} MB")

    RAW.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        tifs = [n for n in z.namelist() if n.lower().endswith(".tif")]
        assert tifs, f"no .tif in the GHSL zip: {z.namelist()}"
        print(f"  zip contains {tifs}")
        raw_tif = RAW / Path(tifs[0]).name
        raw_tif.write_bytes(z.read(tifs[0]))

    tf = Transformer.from_crs(cfg["crs"]["geographic"], GHSL_CRS,
                              always_xy=True)
    w, s, e, n = padded_bbox(cfg)
    xs, ys = zip(*[tf.transform(lo, la)
                   for lo in (w, e) for la in (s, n)])
    with rasterio.open(raw_tif) as src:
        print(f"  tile crs={src.crs} bounds="
              f"{tuple(round(b) for b in src.bounds)} res={src.res} "
              f"dtype={src.dtypes[0]}")
        # R6 — the derived tile index is only trusted once the tile itself
        # says it contains the AOI.
        assert (src.bounds.left <= min(xs) and max(xs) <= src.bounds.right
                and src.bounds.bottom <= min(ys) and max(ys) <= src.bounds.top), \
            (f"GHSL tile {tile} does not contain the AOI "
             f"(x {min(xs):.0f}..{max(xs):.0f}, y {min(ys):.0f}..{max(ys):.0f})")
        win = from_bounds(min(xs), min(ys), max(xs), max(ys),
                          src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win).astype("float32")
        tr = src.window_transform(win)
        nod = src.nodata

    if nod is not None:
        arr[arr == nod] = np.nan
    with rasterio.open(out, "w", driver="GTiff", height=arr.shape[0],
                       width=arr.shape[1], count=1, dtype="float32",
                       crs=GHSL_CRS, transform=tr, nodata=np.nan,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr, 1)
        dst.update_tags(source=f"GHSL {GHSL_STEM} tile {tile}",
                        units="m2 of built-up surface per 100x100 m cell",
                        url=url)
    f = arr[np.isfinite(arr)]
    print(f"  built-up surface m^2/cell over AOI window {arr.shape}: "
          f"min {f.min():.0f}  p50 {np.percentile(f,50):.0f}  "
          f"p99 {np.percentile(f,99):.0f}  max {f.max():.0f} "
          f"(cell = {GHSL_CELL_M2:.0f} m^2)")
    print(f"  wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
    raw_tif.unlink(missing_ok=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ghsl", action="store_true")
    args = ap.parse_args()
    cfg = load_cfg()

    print("=" * 72)
    print(f"PRAVAAH P2-T8 — landcover / impervious ingest   AOI={cfg['id']}")
    print("=" * 72)
    print("\n[ESA WorldCover 10 m v200 2021 — AWS Open Data, unsigned]")
    fetch_worldcover(cfg, args.force)
    if not args.no_ghsl:
        print("\n[GHSL GHS-BUILT-S R2023A 100 m 2020 — JRC direct download]")
        fetch_ghsl(cfg, args.force)


if __name__ == "__main__":
    main()
