#!/usr/bin/env python
"""
PRAVAAH — per-ward population from GHS-POP (completes P2-T11).

WHY NOT WORLDPOP
----------------
WorldPop was the charter's pick (A5) but its server advertises
`Accept-Ranges: bytes` and then ignores range requests, and sustains ~53 KB/s
— roughly 2.8 h for the 531 MB India raster. The exposure table shipped with
population = NULL rather than a fabricated number, which was the right call.

GHS-POP is the same JRC source family as the GHSL built-up layer already in the
stack, is tiled (67 MB for the tile covering Delhi), and downloads in seconds.
Resolution is 100 m — identical to our inundation grid, so no resampling
artefacts in the exposure join.

    python ingest/ghs_pop.py
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.mask import mask

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "landcover"
EXPOSURE = ROOT / "data" / "static" / "exposure.parquet"
BASE = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles")
STEM = "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0"
TILE = "R6_C26"          # covers Delhi; same tile index as the built-up layer


def fetch() -> Path:
    out = RAW / f"{STEM}_{TILE}.tif"
    if out.exists():
        print(f"  cached {out.name}")
        return out
    RAW.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/{STEM}_{TILE}.zip"
    print(f"  downloading {url}")
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        tif = next(n for n in z.namelist() if n.endswith(".tif"))
        out.write_bytes(z.read(tif))
    print(f"  wrote {out.name}  ({out.stat().st_size/1e6:.0f} MB)")
    return out


def main() -> int:
    tif = fetch()
    exp = gpd.read_parquet(EXPOSURE) if EXPOSURE.exists() else None
    if exp is None:
        print("exposure.parquet missing")
        return 1

    with rasterio.open(tif) as src:
        print(f"  raster CRS {src.crs}  res {src.res}")
        wards = exp.to_crs(src.crs)
        pops = []
        for geom in wards.geometry:
            try:
                arr, _ = mask(src, [geom], crop=True, filled=True, nodata=np.nan)
                v = arr[0]
                # GHS-POP cells are PERSONS PER CELL, so the ward total is a SUM.
                # (Using a mean here would be a category error and would
                #  under-count large wards by orders of magnitude.)
                pops.append(float(np.nansum(np.where(v < 0, np.nan, v))))
            except Exception:  # noqa: BLE001
                pops.append(np.nan)

    exp["population"] = np.round(pops).astype("float64")
    exp["population_source"] = "GHS-POP R2023A E2020 100m (JRC)"
    exp.to_parquet(EXPOSURE, index=False)

    tot = np.nansum(pops)
    print(f"\n  per-ward population written for {int(np.isfinite(pops).sum())}/{len(exp)} wards")
    print(f"  Delhi total: {tot:,.0f}  (published ~2.0-3.3 crore for NCT — sanity check)")
    top = exp.nlargest(5, "population")[["ward_name", "population"]]
    print("\n  most populous wards:")
    for _, r in top.iterrows():
        print(f"    {r.ward_name:<28} {r.population:>10,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
