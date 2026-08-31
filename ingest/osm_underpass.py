#!/usr/bin/env python
"""
PRAVAAH — underpass / grade-separation features from OSM.

THE PROBLEM THIS ATTACKS
------------------------
Two independent measurements said terrain does not explain where Delhi floods:
  * Phase 2 gate: of six known waterlogging wards only Minto Road reached the
    top quintile; Jama Masjid sits at 3.1 pct and Turkman Gate at 7.6 pct while
    being 92% and 100% impervious.
  * Label audit: top_quintile_enrichment 0.94 — labelled flood points are, if
    anything, very slightly LESS likely to be in high-susceptibility cells.

The diagnosis was that three of our four checkpoint blackspots (ITO, Zakhira,
Pul Prahladpur) are ROAD UNDERPASSES or RAILWAY UNDERBRIDGES: engineered
depressions 5-15 m wide that a 30 m DSM physically cannot resolve, and whose
flooding is driven by drainage-capacity failure rather than topography.

Storm-sewer capacity is not open data anywhere in India. BUT THE STRUCTURES
THEMSELVES ARE MAPPED. OpenStreetMap tags every one of them:

    tunnel=yes            a road passing under something
    layer < 0             a way explicitly below ground level
    bridge=yes            the structure above — the dip is beside/below it
    railway + bridge      a railway overbridge, i.e. a road underpass beneath

That gives a free, national, systematically-collected proxy for exactly the
class of structure that floods — with no municipal cooperation required. It is
the closest thing to drainage data that exists in the open.

Outputs (100 m, EPSG:32643, aligned to static_stack.nc):
    underpass_dist   metres to the nearest tunnel/below-grade way
    underpass_density  count of such ways within 500 m
    bridge_dist      metres to the nearest bridge structure

    python ingest/osm_underpass.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import rioxarray  # noqa: F401
import xarray as xr
import yaml
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
STATIC = ROOT / "data" / "static" / "static_stack.nc"
RAW = ROOT / "data" / "raw" / "osm_underpass"
OUT = ROOT / "data" / "static"

OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def query(bbox: tuple[float, float, float, float]) -> dict:
    """
    Fetch grade-separated ways. Cached to disk — Overpass rate-limits hard and
    re-querying in a loop is both rude and a fast route to a temporary ban
    (charter R6: fetch once, keep it).
    """
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / "underpass_raw.json"
    if cache.exists():
        print(f"  cached {cache.name}")
        return json.loads(cache.read_text())

    s, w, n, e = bbox
    q = f"""
    [out:json][timeout:180];
    (
      way["highway"]["tunnel"="yes"]({s},{w},{n},{e});
      way["highway"]["layer"~"^-"]({s},{w},{n},{e});
      way["highway"]["bridge"="yes"]({s},{w},{n},{e});
      way["railway"]["bridge"="yes"]({s},{w},{n},{e});
ようd    );
    out geom;
    """.replace("ようd", "")
    for url in OVERPASS:
        try:
            print(f"  querying {url}")
            r = requests.post(url, data={"data": q}, timeout=300,
                              headers={"User-Agent": "PRAVAAH-SIH26071/0.1"})
            if r.status_code == 200 and r.json().get("elements"):
                cache.write_text(r.text)
                return r.json()
            print(f"    HTTP {r.status_code}, {len(r.content)} bytes")
        except Exception as exc:  # noqa: BLE001
            print(f"    {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(5)
    raise RuntimeError("all Overpass endpoints failed")


def to_gdf(payload: dict) -> gpd.GeoDataFrame:
    from shapely.geometry import LineString

    rows = []
    for el in payload.get("elements", []):
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        tags = el.get("tags", {})
        layer = tags.get("layer", "0")
        try:
            layer_i = int(layer)
        except ValueError:
            layer_i = 0
        below = tags.get("tunnel") == "yes" or layer_i < 0
        rows.append({
            "osm_id": el.get("id"),
            "highway": tags.get("highway"),
            "railway": tags.get("railway"),
            "tunnel": tags.get("tunnel"),
            "bridge": tags.get("bridge"),
            "layer": layer_i,
            "below_grade": below,
            "name": tags.get("name"),
            "geometry": LineString([(p["lon"], p["lat"]) for p in geom]),
        })
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    b = cfg["bbox"]
    payload = query((b["south"], b["west"], b["north"], b["east"]))
    gdf = to_gdf(payload)
    print(f"  {len(gdf):,} grade-separated ways")
    print(f"    below-grade (tunnel or layer<0): {int(gdf.below_grade.sum()):,}")
    print(f"    bridges: {int((gdf.bridge == 'yes').sum()):,}")

    named = gdf[gdf.below_grade & gdf.name.notna()].name.value_counts().head(12)
    if len(named):
        print("\n  named below-grade ways (sanity check — expect real underpasses):")
        for k, v in named.items():
            print(f"    {v:>3}x {k}")

    ds = xr.open_dataset(STATIC, decode_coords="all")
    crs = ds.rio.crs
    ref = ds[list(ds.data_vars)[0]]
    ny, nx = ref.shape[-2:]
    tr = ds.rio.transform()
    res = abs(tr.a)
    print(f"\n  target grid {ny}x{nx} @ {res:.0f} m  {crs}")

    g = gdf.to_crs(crs)
    below = g[g.below_grade]
    bridges = g[g.bridge == "yes"]

    from rasterio.features import rasterize

    def burn(sub) -> np.ndarray:
        if sub.empty:
            return np.zeros((ny, nx), dtype=bool)
        return rasterize([(geom, 1) for geom in sub.geometry],
                         out_shape=(ny, nx), transform=tr,
                         fill=0, dtype="uint8").astype(bool)

    m_below, m_bridge = burn(below), burn(bridges)
    print(f"  rasterised: {m_below.sum():,} below-grade cells, "
          f"{m_bridge.sum():,} bridge cells")

    # Euclidean distance transform, in metres.
    d_below = ndimage.distance_transform_edt(~m_below) * res
    d_bridge = ndimage.distance_transform_edt(~m_bridge) * res
    # Density: how many below-grade cells within ~500 m.
    k = int(round(500 / res))
    dens = ndimage.uniform_filter(m_below.astype("float32"),
                                  size=2 * k + 1) * (2 * k + 1) ** 2

    for name, arr in (("underpass_dist", d_below),
                      ("bridge_dist", d_bridge),
                      ("underpass_density", dens)):
        da = xr.DataArray(arr.astype("float32"), dims=ref.dims[-2:],
                          coords={d: ref.coords[d] for d in ref.dims[-2:]})
        da.rio.write_crs(crs, inplace=True)
        da.rio.write_transform(tr, inplace=True)
        ds[name] = da
        print(f"    {name:<20} min {arr.min():.0f}  median {np.median(arr):.0f}  "
              f"max {arr.max():.0f}")

    tmp = STATIC.with_suffix(".nc.tmp")
    ds.to_netcdf(tmp)
    tmp.replace(STATIC)
    print(f"\n  -> {STATIC.relative_to(ROOT)} now has {len(ds.data_vars)} variables")

    # Does it actually find the blackspots we know about?
    print("\n  CHECK — distance to nearest below-grade way at known blackspots:")
    pts = cfg["static_hydro"]["hotspot_checkpoints"]
    gp = gpd.GeoDataFrame(
        pts, geometry=gpd.points_from_xy([p["lon"] for p in pts],
                                         [p["lat"] for p in pts]),
        crs="EPSG:4326").to_crs(crs)
    med = float(np.median(d_below))
    for (_, r), p in zip(gp.iterrows(), pts):
        col = int((r.geometry.x - tr.c) / tr.a)
        row = int((r.geometry.y - tr.f) / tr.e)
        if 0 <= row < ny and 0 <= col < nx:
            v = d_below[row, col]
            print(f"    {p['name']:<18} {v:>7.0f} m   "
                  f"({'CLOSER' if v < med else 'farther'} than the {med:.0f} m median)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
