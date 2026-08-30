#!/usr/bin/env python
"""
PRAVAAH Phase 2 — static hydrology. P2-T2 .. P2-T5, T7, T9, T10.

The terrain half of InundaNet's feature set (PRAVAAH.md 7.3), computed once,
committed, and never touched at demo time (charter R1).

    P2-T2  pysheds: fill pits -> fill depressions -> resolve flats
                    -> flow direction -> flow accumulation
    P2-T3  GRID-SEARCH the stream threshold against OSM waterways by F1,
           write the winner AND the whole table back to the YAML  (charter R7)
    P2-T4  HAND = height above nearest drainage
    P2-T5  TWI, slope, plan curvature
    P2-T7  distance-to-drain, drainage density
    P2-T9  resample every layer onto the shared 100 m grid, stack to NetCDF
    P2-T10 deterministic weighted susceptibility map + reports/susceptibility.png
    GATE   sample the map at known waterlogging blackspots and report percentiles

The one design decision that makes this safe
--------------------------------------------
TWO grids, and the fine one is an EXACT 4x refinement of the coarse one:

    100 m grid : the shared inundation grid. Origin snapped to a 100 m multiple
                 in EPSG:32643, covering the AOI bbox.
    25 m grid  : identical origin and extent, 4x finer. Terrain analysis runs here.

Going 25 m -> 100 m is therefore a pure 4x4 block aggregate. There is no
resampling kernel, no half-pixel offset, no CRS hop, and so no way for the
number-one bug in this phase (silent misalignment) to occur. assert_aligned()
is called after every single layer regardless.

Usage
-----
    python features/static_hydro.py                 # everything, cached
    python features/static_hydro.py --force         # recompute from the DEM
    python features/static_hydro.py --gate-only     # just re-run the exit gate
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.features import rasterize

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
STATIC = ROOT / "data" / "static"
OSM = ROOT / "data" / "raw" / "osm"
REPORTS = ROOT / "reports"

# D8 direction encoding. ESRI convention, the pysheds default. Not a region
# constant — it is the definition of the algorithm's output alphabet.
DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)


# ============================================================ config + grids

def load_cfg() -> dict:
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


class Grids:
    """The two aligned grids. Everything downstream asks this object, never
    a hardcoded transform."""

    def __init__(self, cfg: dict):
        b = cfg["bbox"]
        self.crs_geo = cfg["crs"]["geographic"]
        self.crs = cfg["crs"]["projected"]
        self.res100 = float(cfg["inundation_grid"]["resolution_m"])
        self.res_fine = float(cfg["static_hydro"]["hydro_resolution_m"])

        r = self.res_fine
        assert self.res100 % r == 0, (
            f"hydro_resolution_m ({r}) must divide inundation resolution "
            f"({self.res100}) exactly — that exactness is the whole point")
        self.factor = int(self.res100 // r)

        # Project the lat/lon bbox, then snap OUTWARD to a 100 m lattice so the
        # coarse grid origin is a round number and both grids share it.
        w, s, e, n = transform_bounds(self.crs_geo, self.crs,
                                      b["west"], b["south"], b["east"], b["north"],
                                      densify_pts=64)
        R = self.res100
        self.x0 = float(np.floor(w / R) * R)
        self.y0 = float(np.floor(s / R) * R)
        self.x1 = float(np.ceil(e / R) * R)
        self.y1 = float(np.ceil(n / R) * R)

        self.nx100 = int(round((self.x1 - self.x0) / R))
        self.ny100 = int(round((self.y1 - self.y0) / R))
        self.t100 = from_origin(self.x0, self.y1, R, R)

        self.nx = self.nx100 * self.factor
        self.ny = self.ny100 * self.factor
        self.t = from_origin(self.x0, self.y1, r, r)

    def describe(self) -> None:
        print(f"  projected CRS   {self.crs}")
        print(f"  UTM extent      x {self.x0:.0f} .. {self.x1:.0f}   "
              f"y {self.y0:.0f} .. {self.y1:.0f}")
        print(f"  100 m grid      {self.ny100} rows x {self.nx100} cols  "
              f"({self.ny100*self.nx100:,} cells)")
        print(f"  {self.res_fine:.0f} m grid       {self.ny} rows x {self.nx} cols  "
              f"({self.ny*self.nx:,} cells)   factor {self.factor}x")

    def profile(self, fine: bool = True, dtype: str = "float32",
                nodata=np.nan) -> dict:
        return dict(driver="GTiff", count=1, dtype=dtype, crs=self.crs,
                    nodata=nodata, compress="deflate", tiled=True,
                    height=self.ny if fine else self.ny100,
                    width=self.nx if fine else self.nx100,
                    transform=self.t if fine else self.t100)


def assert_aligned(path: Path, g: Grids, fine: bool) -> None:
    """The alignment tripwire. Called after EVERY layer is written.

    Silent CRS/transform drift is the number-one failure mode of a
    multi-layer geoprocessing stack; this makes it loud and immediate."""
    exp_t = g.t if fine else g.t100
    exp_h = g.ny if fine else g.ny100
    exp_w = g.nx if fine else g.nx100
    with rasterio.open(path) as src:
        assert src.crs.to_string() == rasterio.crs.CRS.from_string(g.crs).to_string(), \
            f"{path.name}: CRS {src.crs} != {g.crs}"
        assert (src.height, src.width) == (exp_h, exp_w), \
            f"{path.name}: shape {(src.height, src.width)} != {(exp_h, exp_w)}"
        for a, b_, nm in zip(src.transform[:6], exp_t[:6], "abcdef"):
            assert abs(a - b_) < 1e-6, \
                f"{path.name}: transform.{nm} {a} != {b_}"


def write(path: Path, arr: np.ndarray, g: Grids, fine: bool = True,
          dtype: str = "float32", nodata=np.nan) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **g.profile(fine, dtype, nodata)) as dst:
        dst.write(arr.astype(dtype), 1)
    assert_aligned(path, g, fine)
    return path


def read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1).astype("float64")


def stats(name: str, a: np.ndarray, unit: str = "") -> None:
    f = a[np.isfinite(a)]
    if f.size == 0:
        print(f"  {name:<16} ALL NaN")
        return
    q = np.percentile(f, [1, 25, 50, 75, 99])
    print(f"  {name:<16} min {f.min():>10.3f}  p1 {q[0]:>9.3f}  p50 {q[2]:>9.3f}  "
          f"p99 {q[4]:>10.3f}  max {f.max():>11.3f} {unit}")


# ============================================================ P2-T1b  reproject

def step_dem(g: Grids, force: bool) -> Path:
    """Warp the padded WGS84 DEM onto the 25 m UTM hydro grid."""
    out = STATIC / "dem_hydro.tif"
    if out.exists() and not force:
        assert_aligned(out, g, fine=True)
        print("  cached  dem_hydro.tif")
        return out

    src_path = STATIC / "dem_pad.tif"
    if not src_path.exists():
        sys.exit("data/static/dem_pad.tif missing — run ingest/dem.py first")

    dst = np.full((g.ny, g.nx), np.nan, dtype="float32")
    with rasterio.open(src_path) as src:
        reproject(source=rasterio.band(src, 1), destination=dst,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=g.t, dst_crs=g.crs,
                  src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)

    nan_frac = float(np.isnan(dst).mean())
    print(f"  warped 4326/30m -> {g.crs}/{g.res_fine:.0f}m   "
          f"nodata {100*nan_frac:.4f} %")
    if nan_frac > 0.001:
        print("  !! more than 0.1 % nodata after the warp — the padded DEM does "
              "not fully cover the UTM box. Increase PAD_DEG in ingest/dem.py.")
    stats("dem_hydro", dst.astype("float64"), "m")
    return write(out, dst, g)


# ============================================================ P2-T2  pysheds

def step_pysheds(g: Grids, force: bool) -> dict[str, Path]:
    """fill pits -> fill depressions -> resolve flats -> fdir -> accumulation."""
    outs = {k: STATIC / f"{k}.tif"
            for k in ("dem_cond", "fdir", "acc", "sink_depth")}
    if all(p.exists() for p in outs.values()) and not force:
        for p in outs.values():
            assert_aligned(p, g, fine=True)
        print("  cached  dem_cond / fdir / acc / sink_depth")
        return outs

    from pysheds.grid import Grid as PGrid

    dem_path = STATIC / "dem_hydro.tif"
    pg = PGrid.from_raster(str(dem_path))
    dem = pg.read_raster(str(dem_path))
    raw = np.asarray(dem, dtype="float64").copy()
    print(f"  pysheds grid {pg.shape}  affine a={pg.affine.a:.1f}")

    t = time.time()
    pits = pg.fill_pits(dem)
    print(f"  fill_pits         {time.time()-t:6.1f}s  "
          f"({int(np.sum(np.asarray(pits) != np.asarray(dem)))} cells raised)")

    t = time.time()
    flooded = pg.fill_depressions(pits)
    print(f"  fill_depressions  {time.time()-t:6.1f}s  "
          f"({int(np.sum(np.asarray(flooded) > np.asarray(pits) + 1e-9))} cells raised)")

    t = time.time()
    inflated = pg.resolve_flats(flooded)
    print(f"  resolve_flats     {time.time()-t:6.1f}s")

    t = time.time()
    fdir = pg.flowdir(inflated, dirmap=DIRMAP)
    print(f"  flowdir           {time.time()-t:6.1f}s  "
          f"codes {sorted(np.unique(np.asarray(fdir)).tolist())[:10]}")

    t = time.time()
    acc = pg.accumulation(fdir, dirmap=DIRMAP)
    print(f"  accumulation      {time.time()-t:6.1f}s")

    cond = np.asarray(inflated, dtype="float64")
    accum = np.asarray(acc, dtype="float64")

    # Depth of the depression that filling removed. In a city this is the
    # underpass / low-point signal — the thing a DEM knows about a waterlogging
    # blackspot that a filled DEM has, by construction, erased.
    sink = np.asarray(flooded, dtype="float64") - raw
    sink[~np.isfinite(sink)] = 0.0
    sink = np.clip(sink, 0, None)

    stats("dem_cond", cond, "m")
    stats("flow_acc", accum, "cells")
    stats("sink_depth", sink, "m")
    cell_km2 = (g.res_fine ** 2) / 1e6
    print(f"  1 accumulation cell = {cell_km2:.6f} km^2 "
          f"({g.res_fine:.0f} m x {g.res_fine:.0f} m)")

    write(outs["dem_cond"], cond, g)
    # fdir carries 0 (not NaN) for "no direction" — that is pysheds' own
    # nodata_out for D8, and round-tripping it as NaN would corrupt the codes.
    write(outs["fdir"], np.asarray(fdir, dtype="float64"), g, nodata=0)
    write(outs["acc"], accum, g)
    write(outs["sink_depth"], sink, g)
    return outs


# ============================================================ OSM rasterisation

def rasterise_waterways(g: Grids, cfg: dict, force: bool) -> Path:
    """Burn the OSM drainage network onto the 25 m grid."""
    out = STATIC / "osm_drains.tif"
    if out.exists() and not force:
        assert_aligned(out, g, fine=True)
        print("  cached  osm_drains.tif")
        return out

    import geopandas as gpd

    src = OSM / "waterways.parquet"
    if not src.exists():
        sys.exit("data/raw/osm/waterways.parquet missing — run ingest/osm.py")

    keep = set(cfg["static_hydro"]["drain_waterway_values"])
    gdf = gpd.read_parquet(src)
    gdf = gdf[gdf["waterway"].isin(keep)]
    gdf = gdf[gdf.geom_type.isin(["LineString", "MultiLineString"])]
    gdf = gdf.to_crs(g.crs)
    print(f"  OSM waterways: {len(gdf)} lines, "
          f"{gdf.length.sum()/1000:.1f} km, values={sorted(keep)}")

    arr = rasterize(((geom, 1) for geom in gdf.geometry),
                    out_shape=(g.ny, g.nx), transform=g.t,
                    fill=0, dtype="uint8", all_touched=True)
    print(f"  burned {int(arr.sum()):,} cells "
          f"({100*arr.mean():.3f} % of the grid)")
    return write(out, arr.astype("float32"), g, dtype="float32", nodata=-1)


# ============================================================ P2-T3  grid search

def buffer_f1(pred: np.ndarray, truth: np.ndarray, tol_cells: float
              ) -> tuple[float, float, float]:
    """Buffered precision / recall / F1 between two binary line networks.

    A DEM-derived channel and an OSM centreline will never share a cell, so a
    cell-exact F1 is ~0 for every candidate and ranks nothing. The standard
    channel-extraction measure is used instead:
        precision = share of predicted stream cells within tol of an OSM line
        recall    = share of OSM line cells within tol of a predicted stream
    """
    from scipy.ndimage import distance_transform_edt

    if pred.sum() == 0 or truth.sum() == 0:
        return 0.0, 0.0, 0.0
    d_truth = distance_transform_edt(~truth)   # distance to nearest OSM cell
    d_pred = distance_transform_edt(~pred)     # distance to nearest DEM stream
    precision = float((d_truth[pred] <= tol_cells).mean())
    recall = float((d_pred[truth] <= tol_cells).mean())
    f1 = 0.0 if (precision + recall) == 0 else \
        2 * precision * recall / (precision + recall)
    return precision, recall, f1


def step_threshold_search(g: Grids, cfg: dict) -> tuple[int, list[dict]]:
    """P2-T3 — fitted, not hardcoded (charter R7)."""
    acc = read(STATIC / "acc.tif")
    truth = read(STATIC / "osm_drains.tif") > 0.5

    sh = cfg["static_hydro"]
    tol_m = float(sh["stream_match_tolerance_m"])
    tol_cells = tol_m / g.res_fine
    search = cfg["fitted"]["stream_threshold_search"]
    cell_km2 = (g.res_fine ** 2) / 1e6

    print(f"  scoring against {int(truth.sum()):,} OSM drain cells, "
          f"tolerance {tol_m:.0f} m = {tol_cells:.1f} cells")
    print()
    print(f"  {'threshold':>10} {'min area':>10} {'stream cells':>13} "
          f"{'precision':>10} {'recall':>8} {'F1':>8}")
    print(f"  {'(cells)':>10} {'(km2)':>10} {'':>13} {'':>10} {'':>8} {'':>8}")
    print("  " + "-" * 64)

    table = []
    for thr in search:
        pred = acc > thr
        p, r, f1 = buffer_f1(pred, truth, tol_cells)
        row = dict(threshold_cells=int(thr),
                   min_drainage_area_km2=round(float(thr) * cell_km2, 4),
                   stream_cells=int(pred.sum()),
                   precision=round(p, 4), recall=round(r, 4), f1=round(f1, 4))
        table.append(row)
        print(f"  {thr:>10d} {row['min_drainage_area_km2']:>10.4f} "
              f"{row['stream_cells']:>13,} {p:>10.4f} {r:>8.4f} {f1:>8.4f}")

    best = max(table, key=lambda d: d["f1"])
    print("  " + "-" * 64)
    print(f"  CHOSEN threshold = {best['threshold_cells']} cells "
          f"({best['min_drainage_area_km2']:.4f} km^2)  F1 = {best['f1']:.4f}")
    return best["threshold_cells"], table


def write_back_yaml(chosen: int, table: list[dict], tol_m: float) -> None:
    """Charter R7: the fitted value AND the table it was chosen from go back
    into the config, so the number always traces to the script that fitted it."""
    text = CONFIG.read_text()
    tbl = json.dumps(table, separators=(", ", ": "))
    stamp = time.strftime("%Y-%m-%d")
    text = text.replace(
        "  stream_threshold_chosen: null      # <- written by features/static_hydro.py\n"
        "  stream_threshold_score_table: null\n",
        f"  # FITTED by features/static_hydro.py on {stamp}: F1 of "
        f"(flow_acc > threshold) against\n"
        f"  # OSM waterways, buffered match tolerance "
        f"{tol_m:.0f} m. Units: 25 m accumulation cells.\n"
        f"  stream_threshold_chosen: {chosen}\n"
        f"  stream_threshold_score_table: {tbl}\n")
    # Idempotent re-run: replace an already-written value.
    import re
    text = re.sub(r"^  stream_threshold_chosen: \d+$",
                  f"  stream_threshold_chosen: {chosen}", text, flags=re.M)
    text = re.sub(r"^  stream_threshold_score_table: \[.*\]$",
                  f"  stream_threshold_score_table: {tbl}", text, flags=re.M)
    CONFIG.write_text(text)
    print(f"  wrote fitted.stream_threshold_chosen = {chosen} "
          f"+ score table back to {CONFIG.name}")


# ============================================================ P2-T4  HAND

def step_hand(g: Grids, threshold: int, force: bool) -> Path:
    out = STATIC / "hand.tif"
    if out.exists() and not force:
        assert_aligned(out, g, fine=True)
        print("  cached  hand.tif")
        stats("hand", read(out), "m")
        return out

    from pysheds.grid import Grid as PGrid

    pg = PGrid.from_raster(str(STATIC / "dem_hydro.tif"))
    fdir = pg.read_raster(str(STATIC / "fdir.tif"))
    dem = pg.read_raster(str(STATIC / "dem_cond.tif"))
    acc = read(STATIC / "acc.tif")
    mask = acc > threshold
    print(f"  stream mask from fitted threshold {threshold}: "
          f"{int(mask.sum()):,} cells")

    t = time.time()
    hand = pg.compute_hand(fdir, dem, mask, dirmap=DIRMAP)
    print(f"  compute_hand      {time.time()-t:6.1f}s")

    h = np.asarray(hand, dtype="float64")
    h[~np.isfinite(h)] = np.nan
    h = np.where(h < 0, 0.0, h)          # numerical noise below the channel
    nan_frac = float(np.isnan(h).mean())
    print(f"  unresolved cells  {100*nan_frac:.3f} % (no downstream stream reached)")
    if nan_frac > 0:
        # Cells that never reach a stream sit on the grid edge or in a closed
        # basin. Give them the AOI's 99th-percentile HAND: "as far above
        # drainage as it gets", which is the honest, conservative answer.
        h = np.where(np.isnan(h), np.nanpercentile(h, 99), h)
    stats("hand", h, "m")
    return write(out, h, g)


# ============================================================ P2-T5  TWI etc.

def step_terrain(g: Grids, force: bool) -> dict[str, Path]:
    outs = {k: STATIC / f"{k}.tif" for k in ("slope", "twi", "plan_curv")}
    if all(p.exists() for p in outs.values()) and not force:
        for p in outs.values():
            assert_aligned(p, g, fine=True)
        print("  cached  slope / twi / plan_curv")
        return outs

    z = read(STATIC / "dem_cond.tif")
    r = g.res_fine
    acc = read(STATIC / "acc.tif")

    # First and second derivatives, central differences at spacing r (metres).
    p, q = np.gradient(z, r, r)[::-1]        # p = dz/dx (east), q = dz/dy (north)
    q = -q                                   # rows run north->south
    pp = np.gradient(p, r, axis=1)           # d2z/dx2
    qq = -np.gradient(q, r, axis=0)          # d2z/dy2
    pq = np.gradient(p, r, axis=0)           # d2z/dxdy
    pq = -pq

    slope_rad = np.arctan(np.hypot(p, q))
    slope_deg = np.degrees(slope_rad)
    stats("slope", slope_deg, "deg")

    # TWI = ln( a / tan(beta) ), a = upslope area per unit contour width.
    # a = (accumulated cells * cell area) / cell width = acc * r  [m]
    # Flat cells make tan(beta) -> 0 and TWI -> inf; floor the slope at the
    # smallest slope a 25 m DEM can actually resolve (1 mm rise over one cell).
    min_tan = 0.001 / r
    tanb = np.maximum(np.tan(slope_rad), min_tan)
    a = np.maximum(acc, 1.0) * r
    twi = np.log(a / tanb)
    stats("twi", twi, "ln(m)")

    # Plan (contour) curvature, Zevenbergen & Thorne form.
    # NEGATIVE = convergent hollow (water collects); positive = divergent ridge.
    denom = (p ** 2 + q ** 2)
    plan = np.where(denom > 1e-12,
                    (q ** 2 * pp - 2 * p * q * pq + p ** 2 * qq)
                    / np.maximum(denom ** 1.5, 1e-12), 0.0)
    plan = np.clip(plan, np.nanpercentile(plan, 0.1),
                   np.nanpercentile(plan, 99.9))
    stats("plan_curv", plan, "1/m")

    write(outs["slope"], slope_deg, g)
    write(outs["twi"], twi, g)
    write(outs["plan_curv"], plan, g)
    return outs


# ============================================================ P2-T7  drains

def step_drain_metrics(g: Grids, cfg: dict, force: bool) -> dict[str, Path]:
    outs = {k: STATIC / f"{k}.tif" for k in ("dist_drain", "drain_density")}
    if all(p.exists() for p in outs.values()) and not force:
        for p in outs.values():
            assert_aligned(p, g, fine=True)
        print("  cached  dist_drain / drain_density")
        return outs

    from scipy.ndimage import distance_transform_edt, uniform_filter

    drains = read(STATIC / "osm_drains.tif") > 0.5
    r = g.res_fine

    dist = distance_transform_edt(~drains) * r
    stats("dist_drain", dist, "m")

    # Drainage density: km of mapped channel per km^2, in a moving window.
    win_m = float(cfg["static_hydro"]["drainage_density_window_m"])
    win = max(3, int(round(win_m / r)))
    length_per_cell = drains.astype("float64") * r          # m of channel
    dens = uniform_filter(length_per_cell, size=win, mode="nearest")
    dens = dens / (r * r) * 1e6 / 1000.0                    # -> km / km^2
    print(f"  drainage density window {win_m:.0f} m = {win} cells")
    stats("drain_density", dens, "km/km2")

    write(outs["dist_drain"], dist, g)
    write(outs["drain_density"], dens, g)
    return outs


# ============================================================ P2-T9  100 m stack

# name -> how a 4x4 block of 25 m cells becomes one 100 m cell.
AGG = {
    "dem":           ("dem_cond.tif",     "mean"),
    "hand":          ("hand.tif",         "min"),   # lowest point governs flooding
    "twi":           ("twi.tif",          "max"),   # wettest point governs
    "slope":         ("slope.tif",        "mean"),
    "plan_curv":     ("plan_curv.tif",    "mean"),
    "flow_acc":      ("acc.tif",          "max"),   # the channel through the block
    "sink_depth":    ("sink_depth.tif",   "max"),
    "dist_drain":    ("dist_drain.tif",   "min"),
    "drain_density": ("drain_density.tif", "mean"),
}


def block_reduce(a: np.ndarray, f: int, how: str) -> np.ndarray:
    b = a.reshape(a.shape[0] // f, f, a.shape[1] // f, f)
    if how == "mean":
        return np.nanmean(b, axis=(1, 3))
    if how == "min":
        return np.nanmin(b, axis=(1, 3))
    if how == "max":
        return np.nanmax(b, axis=(1, 3))
    raise ValueError(how)


def step_stack(g: Grids, cfg: dict, force: bool) -> Path:
    """P2-T9 — every layer onto the shared 100 m grid, one CRS, one transform."""
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    import xarray as xr

    out = STATIC / "static_stack.nc"
    layers = {}
    print(f"  aggregating {g.res_fine:.0f} m -> {g.res100:.0f} m "
          f"by exact {g.factor}x{g.factor} blocks (no interpolation)")
    for name, (fname, how) in AGG.items():
        src = STATIC / fname
        assert_aligned(src, g, fine=True)          # tripwire on the INPUT too
        coarse = block_reduce(read(src), g.factor, how)
        p = write(STATIC / f"g100_{name}.tif", coarse, g, fine=False)
        assert_aligned(p, g, fine=False)           # and on the OUTPUT
        layers[name] = coarse
        print(f"    {name:<14} {how:<5} -> {coarse.shape}  "
              f"[{np.nanmin(coarse):.3f}, {np.nanmax(coarse):.3f}]")

    x = g.x0 + g.res100 * (np.arange(g.nx100) + 0.5)
    y = g.y1 - g.res100 * (np.arange(g.ny100) + 0.5)
    ds = xr.Dataset(
        {k: (("y", "x"), v.astype("float32")) for k, v in layers.items()},
        coords={"y": y, "x": x},
        attrs=dict(
            title="PRAVAAH static hydrology stack",
            aoi=cfg["id"],
            crs=g.crs,
            resolution_m=g.res100,
            transform=str(list(g.t100)[:6]),
            hydro_resolution_m=g.res_fine,
            stream_threshold_cells=cfg["fitted"]["stream_threshold_chosen"],
            source="Copernicus GLO-30 DSM + OpenStreetMap (Overpass)",
            created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        ))
    ds.rio.write_crs(g.crs, inplace=True) if hasattr(ds, "rio") else None
    ds.to_netcdf(out)
    print(f"  wrote {out}  ({out.stat().st_size/1e6:.1f} MB)  "
          f"vars={list(ds.data_vars)}")
    return out


# ============================================================ P2-T10  susceptibility

def pct_norm(a: np.ndarray) -> np.ndarray:
    """Percentile-rank normalisation to [0,1].

    Used instead of min-max because HAND, TWI and distance-to-drain are all
    heavy-tailed: one Aravalli ridge cell or one far-corner cell would
    otherwise compress the entire city into the bottom few percent."""
    flat = a.ravel()
    good = np.isfinite(flat)
    out = np.full(flat.shape, np.nan)
    vals = flat[good]
    order = vals.argsort()
    ranks = np.empty(vals.size, dtype="float64")
    ranks[order] = np.arange(vals.size)
    out[good] = ranks / max(vals.size - 1, 1)
    return out.reshape(a.shape)


def step_susceptibility(g: Grids, cfg: dict) -> Path:
    """P2-T10 — DETERMINISTIC, documented weighted combination (charter R9).
    This is not a model. It is arithmetic on terrain, and we say so."""
    w = cfg["static_hydro"]["susceptibility_weights"]
    tot = sum(w.values())
    assert abs(tot - 1.0) < 1e-9, f"susceptibility weights sum to {tot}, not 1"

    hand = read(STATIC / "g100_hand.tif")
    twi = read(STATIC / "g100_twi.tif")
    slope = read(STATIC / "g100_slope.tif")
    dist = read(STATIC / "g100_dist_drain.tif")

    terms = {
        "hand":       1.0 - pct_norm(hand),
        "twi":        pct_norm(twi),
        "slope":      1.0 - pct_norm(slope),
        "dist_drain": pct_norm(dist),
    }
    s = sum(w[k] * terms[k] for k in terms)
    s = pct_norm(s)          # final map is itself a percentile field in [0,1]

    print("  weighted terms (all percentile-normalised, 1 = more flood-prone):")
    for k, v in w.items():
        print(f"    {k:<11} weight {v:.2f}   "
              f"mean {np.nanmean(terms[k]):.3f}")
    stats("susceptibility", s, "[0,1]")

    p = write(STATIC / "susceptibility.tif", s, g, fine=False)
    render(s, g, cfg)
    return p


def render(s: np.ndarray, g: Grids, cfg: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pyproj import Transformer

    REPORTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 9), dpi=140)
    im = ax.imshow(s, cmap="turbo", vmin=0, vmax=1,
                   extent=[g.x0, g.x1, g.y0, g.y1], interpolation="nearest")

    tf = Transformer.from_crs(g.crs_geo, g.crs, always_xy=True)
    for hp in cfg["static_hydro"]["hotspot_checkpoints"]:
        x, y = tf.transform(hp["lon"], hp["lat"])
        ax.plot(x, y, "o", ms=9, mfc="none", mec="white", mew=2.0)
        ax.annotate(hp["name"], (x, y), xytext=(9, 7),
                    textcoords="offset points", color="white", fontsize=9,
                    weight="bold",
                    path_effects=None)
    ax.set_title("PRAVAAH — static inundation susceptibility (terrain only)\n"
                 f"{cfg['name']} | 100 m | EPSG:32643 | "
                 "deterministic weighted index, no ML", fontsize=11)
    ax.set_xlabel("UTM 43N easting (m)")
    ax.set_ylabel("UTM 43N northing (m)")
    cb = fig.colorbar(im, ax=ax, shrink=0.82)
    cb.set_label("susceptibility percentile (1 = most flood-prone)")
    fig.tight_layout()
    fig.savefig(REPORTS / "susceptibility.png")
    plt.close(fig)
    print(f"  rendered {REPORTS / 'susceptibility.png'}")


# ============================================================ THE EXIT GATE

def exit_gate(g: Grids, cfg: dict) -> bool:
    """Sample the susceptibility map at known Delhi waterlogging blackspots.

    These four points are NEVER an input to anything above. If pure terrain
    ranks them in the top quintile, the geometry is right."""
    from pyproj import Transformer

    s = read(STATIC / "susceptibility.tif")
    finite = s[np.isfinite(s)]
    sh = cfg["static_hydro"]
    need = float(sh["hotspot_pass_percentile"])
    rad_cells = int(round(float(sh["hotspot_sample_radius_m"]) / g.res100))

    tf = Transformer.from_crs(g.crs_geo, g.crs, always_xy=True)
    print(f"\n  map: {s.shape} cells, {finite.size:,} finite, "
          f"pass mark = {need:.0f}th percentile")
    print(f"  {'landmark':<16} {'row,col':>11} {'value':>8} {'pctile':>8} "
          f"{'pctile in':>10} {'':>6}")
    print(f"  {'':<16} {'':>11} {'':>8} {'(cell)':>8} "
          f"{f'{rad_cells*100} m':>10} {'':>6}")
    print("  " + "-" * 66)

    ok = True
    rows = []
    for hp in sh["hotspot_checkpoints"]:
        x, y = tf.transform(hp["lon"], hp["lat"])
        col = int((x - g.x0) / g.res100)
        row = int((g.y1 - y) / g.res100)
        if not (0 <= row < g.ny100 and 0 <= col < g.nx100):
            print(f"  {hp['name']:<16} OUTSIDE THE GRID")
            ok = False
            continue
        v = float(s[row, col])
        pc = float((finite <= v).mean() * 100)
        r0, r1 = max(row - rad_cells, 0), min(row + rad_cells + 1, g.ny100)
        c0, c1 = max(col - rad_cells, 0), min(col + rad_cells + 1, g.nx100)
        vn = float(np.nanmax(s[r0:r1, c0:c1]))
        pcn = float((finite <= vn).mean() * 100)
        flag = "PASS" if pc >= need else ("pass*" if pcn >= need else "FAIL")
        if pc < need and pcn < need:
            ok = False
        rows.append((hp["name"], pc, pcn, flag))
        print(f"  {hp['name']:<16} {row:>5},{col:<5} {v:>8.4f} {pc:>7.1f}% "
              f"{pcn:>9.1f}% {flag:>6}")

    print("  " + "-" * 66)
    print("  PASS  = the landmark's own 100 m cell is at/above the pass mark")
    print("  pass* = the cell misses but the neighbourhood max clears it "
          "(landmark coords are approximate)")
    print(f"\n  EXIT GATE: {'PASS' if ok else 'FAIL'} — "
          f"{sum(1 for r in rows if r[3] == 'PASS')}/{len(rows)} on the exact "
          f"cell, {sum(1 for r in rows if r[3] != 'FAIL')}/{len(rows)} "
          f"within {rad_cells*100} m")

    (REPORTS / "phase2_gate.json").write_text(json.dumps(
        dict(pass_percentile=need,
             hotspots=[dict(name=n, percentile_cell=round(a, 2),
                            percentile_neighbourhood=round(b, 2), result=f)
                       for n, a, b, f in rows],
             passed=ok), indent=2))
    return ok


# ============================================================ main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gate-only", action="store_true")
    ap.add_argument("--from-stack", action="store_true",
                    help="skip terrain, redo stack + susceptibility + gate")
    args = ap.parse_args()

    cfg = load_cfg()
    g = Grids(cfg)

    print("=" * 72)
    print(f"PRAVAAH Phase 2 — static hydrology   AOI={cfg['id']}")
    print("=" * 72)
    g.describe()

    if args.gate_only:
        exit_gate(g, cfg)
        return

    if not args.from_stack:
        print("\n[P2-T1b] warp DEM onto the hydro grid")
        step_dem(g, args.force)

        print("\n[P2-T2] pysheds conditioning + flow routing")
        step_pysheds(g, args.force)

        print("\n[P2-T3] OSM waterways -> raster")
        rasterise_waterways(g, cfg, args.force)

        print("\n[P2-T3] grid-search the stream threshold (charter R7)")
        chosen, table = step_threshold_search(g, cfg)
        write_back_yaml(chosen, table,
                        float(cfg["static_hydro"]["stream_match_tolerance_m"]))
        cfg = load_cfg()

        print("\n[P2-T4] HAND")
        step_hand(g, chosen, args.force)

        print("\n[P2-T5] slope, TWI, plan curvature")
        step_terrain(g, args.force)

        print("\n[P2-T7] distance-to-drain, drainage density")
        step_drain_metrics(g, cfg, args.force)

    print("\n[P2-T9] resample everything to the shared 100 m grid + stack")
    step_stack(g, cfg, args.force)

    print("\n[P2-T10] static susceptibility map")
    step_susceptibility(g, cfg)

    print("\n" + "=" * 72)
    print("EXIT GATE — Delhi waterlogging blackspots, never used as an input")
    print("=" * 72)
    ok = exit_gate(g, cfg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
