#!/usr/bin/env python
"""
PRAVAAH — build an OFFLINE vector basemap from OSM data we already hold.

WHY NOT A TILE SERVER
---------------------
The obvious answers (CARTO, OpenFreeMap, Google) all need the network, and the
demo has a hard airplane-mode gate. Protomaps PMTiles would work offline but
adds a toolchain and a multi-GB planet extract.

We do not need any of it: ingest/osm.py already pulled 19,823 km of Delhi roads,
the waterway network, hospitals/schools/pumps, and ingest/osm_underpass.py added
1,305 below-grade ways. That is a real street map sitting on disk. This script
turns it into size-controlled GeoJSON the existing MapLibre canvas can draw
underneath the choropleth — same engine, no new dependency, still 100% local.

SIZE IS THE WHOLE PROBLEM
-------------------------
roads.parquet is 29 MB; shipping that to a browser would make the map unusable.
Two levers, both applied per tier:
  * CLASS FILTER  — motorway/trunk/primary are drawn at every zoom; residential
    and below only exist in the detail tier.
  * GEOMETRY SIMPLIFICATION — Douglas-Peucker at a tolerance matched to the
    tier's intended zoom, so we never carry precision the viewer cannot see.

    python scripts/build_basemap.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OSM = ROOT / "data" / "raw" / "osm"
UNDER = ROOT / "data" / "raw" / "osm_underpass" / "underpass_raw.json"
OUT = ROOT / "data" / "outputs" / "basemap"

# tier -> (highway classes, simplify tolerance in degrees)
TIERS = {
    "major": (["motorway", "trunk", "primary", "motorway_link", "trunk_link"], 0.0004),
    "secondary": (["secondary", "tertiary", "secondary_link", "tertiary_link"], 0.0003),
    # NOTE: residential/unclassified are DELIBERATELY EXCLUDED. Delhi has
    # 239,283 of them and they serialise to 43 MB — unusable in a browser, and
    # at city zoom they are visual noise that obscures the choropleth we
    # actually came to show. Major + secondary is 27k features / ~4.9 MB and
    # reads as a real street map.
}
MAX_TOTAL_KB = 12_000


def write(gdf: gpd.GeoDataFrame, name: str, keep: list[str] | None = None) -> None:
    if gdf.empty:
        print(f"  {name:<22} EMPTY — skipped")
        return
    cols = [c for c in (keep or []) if c in gdf.columns] + ["geometry"]
    g = gdf[cols].copy()
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.geojson"
    g.to_file(p, driver="GeoJSON")
    kb = p.stat().st_size / 1024
    print(f"  {name:<22} {len(g):>7,} features  {kb:>8.0f} KB")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- roads
    rp = OSM / "roads.parquet"
    if rp.exists():
        roads = gpd.read_parquet(rp)
        if roads.crs is None:
            roads.set_crs("EPSG:4326", inplace=True)
        roads = roads.to_crs("EPSG:4326")
        col = next((c for c in ("highway", "fclass", "type")
                    if c in roads.columns), None)
        print(f"  roads.parquet: {len(roads):,} features, class column '{col}'")
        if col:
            # Some OSM extracts store the tag as a list; normalise to a string.
            roads[col] = roads[col].map(
                lambda v: v[0] if isinstance(v, list) and v else v).astype(str)
            for tier, (classes, tol) in TIERS.items():
                sub = roads[roads[col].isin(classes)].copy()
                if sub.empty:
                    print(f"  {tier}: no matches for {classes[:3]}...")
                    continue
                sub["geometry"] = sub.geometry.simplify(tol, preserve_topology=False)
                sub = sub[~sub.geometry.is_empty & sub.geometry.notna()]
                write(sub, f"roads_{tier}", [col])
    else:
        print("  roads.parquet missing")

    # ------------------------------------------------------------ waterways
    wp = OSM / "waterways.parquet"
    if wp.exists():
        w = gpd.read_parquet(wp).to_crs("EPSG:4326")
        w["geometry"] = w.geometry.simplify(0.0002, preserve_topology=False)
        w = w[~w.geometry.is_empty & w.geometry.notna()]
        wcol = next((c for c in ("waterway", "fclass") if c in w.columns), None)
        if wcol:
            w[wcol] = w[wcol].map(
                lambda v: v[0] if isinstance(v, list) and v else v).astype(str)
        write(w, "waterways", [wcol] if wcol else [])

    # --------------------------------------------------------------- assets
    for name in ("hospitals", "schools", "pumps"):
        p = OSM / f"{name}.parquet"
        if not p.exists():
            continue
        g = gpd.read_parquet(p).to_crs("EPSG:4326")
        # Points render far more cheaply than polygons and a hospital footprint
        # adds nothing at city zoom.
        g["geometry"] = g.geometry.representative_point()
        ncol = "name" if "name" in g.columns else None
        write(g, name, [ncol] if ncol else [])

    # ----------------------------------------------- underpasses (the story)
    if UNDER.exists():
        from shapely.geometry import LineString
        payload = json.loads(UNDER.read_text())
        rows = []
        for el in payload.get("elements", []):
            geom = el.get("geometry")
            if not geom or len(geom) < 2:
                continue
            t = el.get("tags", {})
            try:
                layer = int(t.get("layer", "0"))
            except ValueError:
                layer = 0
            if not (t.get("tunnel") == "yes" or layer < 0):
                continue
            rows.append({"name": t.get("name"), "highway": t.get("highway"),
                         "geometry": LineString(
                             [(p["lon"], p["lat"]) for p in geom])})
        if rows:
            write(gpd.GeoDataFrame(rows, crs="EPSG:4326"),
                  "underpasses", ["name", "highway"])

    manifest = {p.stem: {"file": f"/static/basemap/{p.name}",
                         "kb": round(p.stat().st_size / 1024)}
                for p in sorted(OUT.glob("*.geojson"))}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total = sum(v["kb"] for v in manifest.values())
    print(f"\n  {len(manifest)} layers, {total:,} KB total -> "
          f"{OUT.relative_to(ROOT)}")
    if total > MAX_TOTAL_KB:
        print(f"  WARNING: over the {MAX_TOTAL_KB:,} KB budget — the map will "
              f"stutter. Drop a tier or simplify harder.")
    print("  served by FastAPI at /static/basemap/*.geojson (already mounted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
