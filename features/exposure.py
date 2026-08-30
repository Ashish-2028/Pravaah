#!/usr/bin/env python
"""
PRAVAAH P2-T11 — per-ward exposure table.

Ward polygons x OSM assets x terrain susceptibility -> data/static/exposure.parquet

The ward is the unit the product delivers at (PRAVAAH.md 3). This table is what
turns "cell 412,377 has P(flood) 0.78" into "Karol Bagh: 41 000 people,
3 hospitals, 11 schools, 62 km of road at risk".

Charter rules honoured
----------------------
R9  Every number here is DETERMINISTIC — a spatial join and a sum. Nothing is
    learned, nothing is modelled, and the report says so.
R7  Ward file, id/name fields and CRS all come from the YAML.
R3  Prints real counts and the ward-level ranking, not a claim of success.

Population honesty
------------------
WorldPop 100 m is attempted by a windowed HTTP read of the public COG. If that
fails or is too slow, the column is written as NULL with `population_source =
"UNAVAILABLE"` and the run says so loudly. A fabricated population number would
propagate into every downstream impact figure in the product; a NULL will not.

Usage
-----
    python features/exposure.py
    python features/exposure.py --no-population   # skip the WorldPop attempt
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
STATIC = ROOT / "data" / "static"
RAW = ROOT / "data" / "raw"
OSM = RAW / "osm"
REPORTS = ROOT / "reports"

# WorldPop constrained 100 m, India, 2020. Public, no key, no account.
#
# PROBED 31 Aug 2026 (charter R6 — inspect the real response, then decide):
#   * Content-Length 531 062 384 bytes (~531 MB).
#   * The response advertises `Accept-Ranges: bytes` but DOES NOT honour it:
#     `curl -r 0-99` returns HTTP 200 with a full-body stream, not HTTP 206.
#     That is why GDAL's /vsicurl/ reports "Range downloading not supported by
#     this server" — the error is accurate, not a GDAL misconfiguration, and no
#     amount of CPL_VSIL_CURL_* tuning will produce a windowed read.
#   * Measured sustained throughput ~53 kB/s => ~2.8 h for the whole file.
#
# So there is no fast path. The file is used ONLY if someone has already put it
# on disk at WORLDPOP_LOCAL; otherwise the population column is NULL and says
# so. Drop the .tif in and re-run — nothing else needs to change.
WORLDPOP_URL = ("https://data.worldpop.org/GIS/Population/"
                "Global_2000_2020_Constrained/2020/BSGM/IND/"
                "ind_ppp_2020_constrained.tif")
WORLDPOP_LOCAL = RAW / "worldpop" / "ind_ppp_2020_constrained.tif"
WORLDPOP_MIN_BYTES = 500_000_000     # a partial download must not be trusted


def load_cfg() -> dict:
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


def load_wards(cfg: dict) -> gpd.GeoDataFrame:
    src = cfg["sources"]["ward_polygons"]
    path = RAW / "Delhi_Wards.geojson"
    if not path.exists():
        sys.exit(f"{path} missing — see sources.ward_polygons.url in the YAML")
    g = gpd.read_file(path)
    idf, namef = src["id_field"], src["name_field"]
    missing = [f for f in (idf, namef) if f not in g.columns]
    if missing:
        sys.exit(f"ward file lacks {missing}; has {list(g.columns)}")
    g = g[[idf, namef, "geometry"]].rename(
        columns={idf: "ward_no", namef: "ward_name"})
    g = g.to_crs(cfg["crs"]["projected"])
    g["area_km2"] = g.area / 1e6
    print(f"  wards: {len(g)}  crs={g.crs.to_string()}  "
          f"total area {g['area_km2'].sum():,.0f} km2  "
          f"(median ward {g['area_km2'].median():.2f} km2)")
    return g


def count_assets(wards: gpd.GeoDataFrame, name: str, crs: str) -> pd.Series:
    """Points-in-ward count. Polygon assets collapse to a representative point
    so a hospital campus straddling a boundary is counted exactly once."""
    p = OSM / f"{name}.parquet"
    if not p.exists():
        print(f"  {name:<11} MISSING ({p.name}) -> column will be 0")
        return pd.Series(0, index=wards.index, dtype="int64")
    g = gpd.read_parquet(p).to_crs(crs)
    g = g[~g.geometry.is_empty & g.geometry.notna()]
    g["geometry"] = g.geometry.representative_point()
    j = gpd.sjoin(g[["geometry"]], wards[["geometry"]], predicate="within",
                  how="inner")
    counts = j.groupby("index_right").size()
    out = pd.Series(0, index=wards.index, dtype="int64")
    out.loc[counts.index] = counts.values
    print(f"  {name:<11} {len(g):>6} features -> {int(out.sum()):>6} inside "
          f"wards ({len(g) - int(out.sum())} fall outside Delhi)")
    return out


def road_km(wards: gpd.GeoDataFrame, crs: str) -> pd.Series:
    # roads.parquet = drivable ways from ox.features_from_bbox (what we use).
    # roads_edges.parquet = the routable graph's edges, only present if someone
    # ran `ingest/osm.py --graph`. Either gives the same length sum.
    out = pd.Series(np.nan, index=wards.index, dtype="float64")
    p = next((q for q in (OSM / "roads.parquet", OSM / "roads_edges.parquet")
              if q.exists()), None)
    if p is None:
        print("  roads       MISSING (roads.parquet) -> column will be "
              "NULL, not zero")
        return out
    e = gpd.read_parquet(p).to_crs(crs)
    e = e[e.geometry.notna() & ~e.geometry.is_empty]
    e = e[e.geom_type.isin(["LineString", "MultiLineString"])]
    print(f"  roads       {len(e):>6} edges, {e.length.sum()/1000:,.0f} km "
          f"in the AOI; clipping to wards ...", flush=True)
    t = time.time()
    # A true intersection, not a centroid join: a 3 km edge crossing four wards
    # must contribute its real share to each.
    parts = gpd.overlay(e[["geometry"]], wards[["ward_no", "geometry"]],
                        how="intersection", keep_geom_type=False)
    parts["km"] = parts.length / 1000.0
    by = parts.groupby("ward_no")["km"].sum()
    lut = wards["ward_no"].map(by)
    out = lut.fillna(0.0)
    print(f"  roads       clipped in {time.time()-t:.0f}s -> "
          f"{out.sum():,.0f} km inside Delhi wards")
    return out


def zonal_susceptibility(wards: gpd.GeoDataFrame, cfg: dict) -> pd.DataFrame:
    """Mean and top-quintile share of the terrain susceptibility per ward."""
    import rasterio
    from rasterio.features import rasterize

    p = STATIC / "susceptibility.tif"
    if not p.exists():
        print("  susceptibility.tif missing — run features/static_hydro.py")
        return pd.DataFrame(index=wards.index)

    with rasterio.open(p) as src:
        s = src.read(1)
        transform, shape, rcrs = src.transform, src.shape, src.crs
    assert rcrs.to_string() == \
        rasterio.crs.CRS.from_string(cfg["crs"]["projected"]).to_string(), \
        f"susceptibility CRS {rcrs} != config projected CRS"

    idx = rasterize(
        ((geom, i + 1) for i, geom in enumerate(wards.geometry)),
        out_shape=shape, transform=transform, fill=0, dtype="int32")
    print(f"  zonal: {int((idx > 0).sum()):,} of {idx.size:,} cells "
          f"({100*(idx > 0).mean():.1f} %) fall inside a ward")

    df = pd.DataFrame({"w": idx.ravel(), "s": s.ravel()})
    df = df[(df["w"] > 0) & np.isfinite(df["s"])]
    agg = df.groupby("w")["s"].agg(
        susceptibility_mean="mean",
        susceptibility_p90=lambda v: float(np.percentile(v, 90)),
        cells="size")
    agg["top_quintile_share"] = df.assign(hi=df["s"] >= 0.8) \
        .groupby("w")["hi"].mean()
    agg.index = agg.index - 1
    return agg.reindex(wards.index)


def fetch_population(wards: gpd.GeoDataFrame, cfg: dict) -> tuple[pd.Series, str]:
    """Windowed HTTP read of the public WorldPop raster. Returns (values, source).

    On ANY failure this returns all-NaN and the string 'UNAVAILABLE'. It never
    invents a number — a fabricated population would silently corrupt every
    impact figure downstream (charter R3/R9)."""
    import os

    try:
        import rasterio
        from rasterio.features import rasterize
        from rasterio.warp import transform_bounds

        os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
        os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
        os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")

        b = cfg["bbox"]
        t = time.time()
        if WORLDPOP_LOCAL.exists():
            size = WORLDPOP_LOCAL.stat().st_size
            if size < WORLDPOP_MIN_BYTES:
                raise RuntimeError(
                    f"{WORLDPOP_LOCAL.name} is only {size/1e6:.0f} MB — a "
                    f"partial download. Refusing to read it; finish the "
                    f"transfer (expect ~531 MB) and re-run.")
            path = str(WORLDPOP_LOCAL)
            print(f"  using local WorldPop raster {WORLDPOP_LOCAL} "
                  f"({size/1e6:.0f} MB)", flush=True)
        else:
            path = f"/vsicurl/{WORLDPOP_URL}"
            print(f"  no local raster; trying a windowed read of "
                  f"{WORLDPOP_URL}", flush=True)
            print("  (expected to fail — this server ignores byte ranges; "
                  "see the note at the top of this file)", flush=True)
        with rasterio.open(path) as src:
            print(f"    opened: {src.width}x{src.height} {src.crs} "
                  f"nodata={src.nodata} ({time.time()-t:.0f}s)")
            w, s_, e, n = transform_bounds(cfg["crs"]["geographic"], src.crs,
                                           b["west"], b["south"],
                                           b["east"], b["north"])
            win = rasterio.windows.from_bounds(w, s_, e, n,
                                               transform=src.transform)
            pop = src.read(1, window=win)
            wt = rasterio.windows.transform(win, src.transform)
            pcrs = src.crs
            nod = src.nodata
        pop = pop.astype("float64")
        if nod is not None:
            pop[pop == nod] = 0.0
        pop[~np.isfinite(pop)] = 0.0
        print(f"    window {pop.shape}  sum {pop.sum():,.0f} people  "
              f"({time.time()-t:.0f}s total)")

        wl = wards.to_crs(pcrs)
        idx = rasterize(((geom, i + 1) for i, geom in enumerate(wl.geometry)),
                        out_shape=pop.shape, transform=wt, fill=0,
                        dtype="int32")
        df = pd.DataFrame({"w": idx.ravel(), "p": pop.ravel()})
        tot = df[df["w"] > 0].groupby("w")["p"].sum()
        tot.index = tot.index - 1
        out = tot.reindex(wards.index).fillna(0.0)
        print(f"    per-ward total {out.sum():,.0f} people "
              f"(NCT of Delhi reference ~19-20 M — if this is out by more "
              f"than ~20 % the raster or the join is wrong, not Delhi)")
        return out, "WorldPop 2020 constrained 100 m (ind_ppp_2020_constrained)"
    except Exception as exc:  # noqa: BLE001
        print(f"  !! WorldPop unavailable: {type(exc).__name__}: "
              f"{str(exc)[:200]}")
        print("  !! population column written as NULL. It is NOT estimated, "
              "NOT interpolated and NOT filled with a plausible-looking "
              "number. Any downstream 'people affected' figure must stay "
              "blank until a real source lands.")
        return pd.Series(np.nan, index=wards.index, dtype="float64"), \
            "UNAVAILABLE"


def ward_gate(df: pd.DataFrame, cfg: dict) -> None:
    """Complementary, ward-level version of the exit gate.

    The config names five wards known for waterlogging (labels.hotspot_wards).
    They were never used to build anything. Ranking 290 wards is a much less
    fragile test than sampling four points, so it is reported alongside."""
    names = [n.upper() for n in cfg["labels"]["hotspot_wards"]]
    if "susceptibility_mean" not in df:
        return
    d = df.dropna(subset=["susceptibility_mean"]).copy()
    d["rank"] = d["susceptibility_mean"].rank(pct=True) * 100
    print(f"\n  ward-level check — {len(d)} wards ranked by mean terrain "
          f"susceptibility")
    print(f"  {'ward (from labels.hotspot_wards)':<36}{'mean':>8}"
          f"{'pctile':>9}{'top-20% area':>14}")
    hit = 0
    for nm in names:
        m = d[d["ward_name"].str.upper().str.strip() == nm]
        if m.empty:
            print(f"  {nm:<36}{'NOT IN WARD FILE':>31}")
            continue
        r = m.iloc[0]
        hit += r["rank"] >= 80
        print(f"  {nm:<36}{r['susceptibility_mean']:>8.3f}{r['rank']:>8.1f}%"
              f"{100*r['top_quintile_share']:>13.1f}%")
    print(f"  -> {hit}/{len([n for n in names])} named waterlogging wards in "
          f"the top quintile of wards")
    print("\n  top 10 wards by mean terrain susceptibility:")
    for _, r in d.nlargest(10, "susceptibility_mean").iterrows():
        print(f"    {r['ward_name']:<32} {r['susceptibility_mean']:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-population", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg()
    crs = cfg["crs"]["projected"]
    print("=" * 72)
    print(f"PRAVAAH P2-T11 — exposure table   AOI={cfg['id']}")
    print("=" * 72)

    wards = load_wards(cfg)

    print("\n[assets] OSM point counts per ward")
    out = wards[["ward_no", "ward_name", "area_km2"]].copy()
    out["hospitals"] = count_assets(wards, "hospitals", crs)
    out["schools"] = count_assets(wards, "schools", crs)
    out["pumps"] = count_assets(wards, "pumps", crs)
    out["road_km"] = road_km(wards, crs).round(3)

    print("\n[terrain] zonal susceptibility per ward")
    out = out.join(zonal_susceptibility(wards, cfg))

    print("\n[population]")
    if args.no_population:
        out["population"] = np.nan
        src = "SKIPPED (--no-population)"
        print("  skipped by flag")
    else:
        pop, src = fetch_population(wards, cfg)
        out["population"] = pop.round(1)
    out["population_source"] = src

    out["geometry"] = wards.geometry
    gout = gpd.GeoDataFrame(out, geometry="geometry", crs=crs)
    dst = STATIC / "exposure.parquet"
    gout.to_parquet(dst)

    print(f"\n  wrote {dst}  ({len(gout)} wards, "
          f"{dst.stat().st_size/1e3:.0f} kB)")
    print(f"  columns: {[c for c in gout.columns if c != 'geometry']}")
    print(f"  totals: {int(out['hospitals'].sum())} hospitals, "
          f"{int(out['schools'].sum())} schools, "
          f"{int(out['pumps'].sum())} pumps, "
          f"{out['road_km'].sum():,.0f} km road")
    print(f"  population source: {src}")
    if src == "UNAVAILABLE":
        print("  population column is NULL for all 290 wards — see above.")

    ward_gate(out, cfg)


if __name__ == "__main__":
    main()
