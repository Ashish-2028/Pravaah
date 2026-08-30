#!/usr/bin/env python
"""
PRAVAAH A7 / P2-T1 — Copernicus GLO-30 DEM ingest.

Pulls the DEM tiles named in configs/aoi_delhi_ncr.yaml from the PUBLIC,
UNSIGNED S3 bucket s3://copernicus-dem-30m (no credentials, no account),
merges them, and clips to the AOI bbox.

Charter rules honoured
----------------------
R7  Every coordinate and every tile name is read from the YAML. Nothing about
    Delhi is hardcoded in this file — swap the YAML, get a new region.
R6  The download is cached: re-running skips tiles already on disk.
R3  Prints the real elevation range and shape. A GLO-30 read that silently
    returns the nodata fill (-32767) or a byte-swapped array shows up here
    immediately as an insane range.

Usage
-----
    python ingest/dem.py            # download (cached) + merge + clip
    python ingest/dem.py --force    # re-download the tiles
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.merge import merge
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
STATIC = ROOT / "data" / "static"
RAW = ROOT / "data" / "raw" / "dem"

BUCKET = "copernicus-dem-30m"

# Sanity envelope for the merged DEM. This is NOT a region constant used in any
# computation — it is a tripwire. Delhi NCR is Indo-Gangetic plain: nothing on
# the ground is below sea level and nothing is a mountain. A read that comes
# back outside this band means a broken decode, not surprising terrain.
SANE_MIN_M = -50.0
SANE_MAX_M = 1500.0

# Halo, in degrees, around the AOI for the processing DEM. See main().
PAD_DEG = 0.05


def load_cfg() -> dict:
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


def download_tiles(tiles: list[str], force: bool = False) -> list[Path]:
    """Fetch each named tile from the unsigned public bucket. Cached."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    RAW.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))

    paths = []
    for t in tiles:
        dst = RAW / f"{t}.tif"
        if dst.exists() and not force:
            print(f"  cached   {dst.name}  ({dst.stat().st_size/1e6:.1f} MB)")
        else:
            key = f"{t}/{t}.tif"
            print(f"  download s3://{BUCKET}/{key} ...", flush=True)
            s3.download_file(BUCKET, key, str(dst))
            print(f"           -> {dst.name}  ({dst.stat().st_size/1e6:.1f} MB)")
        paths.append(dst)
    return paths


def merge_and_clip(tile_paths: list[Path], bbox: dict, out: Path,
                   pad_deg: float = 0.0) -> Path:
    """Merge the tiles, clip to bbox (optionally padded), write a GeoTIFF."""
    bbox = {"west": bbox["west"] - pad_deg, "east": bbox["east"] + pad_deg,
            "south": bbox["south"] - pad_deg, "north": bbox["north"] + pad_deg}
    srcs = [rasterio.open(p) for p in tile_paths]
    for s in srcs:
        print(f"  tile {Path(s.name).stem}: {s.width}x{s.height} "
              f"crs={s.crs} bounds={tuple(round(b, 3) for b in s.bounds)} "
              f"dtype={s.dtypes[0]} nodata={s.nodata}")

    mosaic, transform = merge(srcs)
    crs = srcs[0].crs
    nodata = srcs[0].nodata
    for s in srcs:
        s.close()

    print(f"  merged mosaic: {mosaic.shape}")

    # Clip with a window derived from the merged transform (no reprojection —
    # the tiles and the bbox are both EPSG:4326).
    win = from_bounds(bbox["west"], bbox["south"], bbox["east"], bbox["north"],
                      transform=transform)
    r0, r1 = int(np.floor(win.row_off)), int(np.ceil(win.row_off + win.height))
    c0, c1 = int(np.floor(win.col_off)), int(np.ceil(win.col_off + win.width))
    r0, c0 = max(r0, 0), max(c0, 0)
    r1, c1 = min(r1, mosaic.shape[1]), min(c1, mosaic.shape[2])

    clipped = mosaic[:, r0:r1, c0:c1]
    clip_transform = rasterio.windows.transform(
        rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0), transform)

    arr = clipped[0].astype("float32")
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    # GLO-30 ships -32767 as its fill even when nodata is unset on the COG.
    arr = np.where(arr < -1000, np.nan, arr)

    out.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                   count=1, dtype="float32", crs=crs, transform=clip_transform,
                   nodata=np.nan, compress="deflate", tiled=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(arr, 1)

    return out


def report(path: Path) -> None:
    with rasterio.open(path) as src:
        a = src.read(1, masked=True)
        west, south, east, north = src.bounds
        print("\n--- DEM AOI clip ---")
        print(f"  path       {path}")
        print(f"  shape      {src.height} x {src.width}")
        print(f"  crs        {src.crs}")
        print(f"  bounds     W {west:.4f}  S {south:.4f}  E {east:.4f}  N {north:.4f}")
        print(f"  pixel      {src.transform.a:.8f} deg  "
              f"(~{src.transform.a*111320:.1f} m at the equator)")
        print(f"  elevation  min {a.min():.2f} m   max {a.max():.2f} m   "
              f"mean {a.mean():.2f} m   median {np.ma.median(a):.2f} m")
        print(f"  nodata     {int(a.mask.sum())} cells "
              f"({100*a.mask.mean():.3f} %)")

        lo, hi = float(a.min()), float(a.max())
        if not (SANE_MIN_M < lo < SANE_MAX_M and SANE_MIN_M < hi < SANE_MAX_M):
            print(f"\n  !! ELEVATION RANGE FAILS THE SANITY TRIPWIRE "
                  f"[{SANE_MIN_M}, {SANE_MAX_M}] m — the read is broken, "
                  f"not the terrain.")
            sys.exit(2)
        print(f"  SANITY OK  range sits inside [{SANE_MIN_M}, {SANE_MAX_M}] m")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-download tiles even if cached")
    args = ap.parse_args()

    cfg = load_cfg()
    bbox = cfg["bbox"]
    tiles = cfg["sources"]["dem_tiles"]

    print(f"AOI {cfg['id']}  bbox W{bbox['west']} S{bbox['south']} "
          f"E{bbox['east']} N{bbox['north']}")
    print(f"tiles from config: {tiles}\n")

    paths = download_tiles(tiles, force=args.force)

    # Exact AOI clip — the QA / reporting artefact.
    out = merge_and_clip(paths, bbox, STATIC / "dem_aoi.tif")
    report(out)

    # Padded clip — the PROCESSING artefact. Flow routing needs terrain beyond
    # the AOI edge or every boundary cell is a false outlet, and reprojecting
    # a lat/lon box into UTM 43N produces an axis-aligned box that pokes ~1.7 km
    # past the lat/lon corners (meridian convergence ~1.3 deg out here).
    # PAD_DEG is a projection-geometry allowance, not a region fact.
    pad = merge_and_clip(paths, bbox, STATIC / "dem_pad.tif", pad_deg=PAD_DEG)
    report(pad)


if __name__ == "__main__":
    main()
