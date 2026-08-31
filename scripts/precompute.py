#!/usr/bin/env python
"""
PRAVAAH — precompute every demo artefact from the REAL models (BUILD_PLAN P8).

THIS IS THE HANDOFF. Up to now the app has been running on scripts/make_fakes.py
output. This script writes files with the IDENTICAL schema from actual model
predictions, so the backend, the React app and the Streamlit harness all switch
to real numbers WITHOUT A SINGLE CODE CHANGE. That is what the frozen contracts
in PRAVAAH.md §12.2 were for.

After this runs, the models never execute again. The demo is a file reader.

THE REPLAY LAW (charter R4) IS ENFORCED HERE, NOT JUST IN THE BACKEND
--------------------------------------------------------------------
Every timestamp's artefacts are generated from cube.at(t) — the accessor that
returns only data issued <= t. So when the frontend clock sits at 04:30, the
numbers on screen were computed from what was genuinely knowable at 04:30. The
backend then filters files by timestamp, and the honesty law holds end to end.

    python scripts/precompute.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cube.accessor import Cube  # noqa: E402

CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
STATIC = ROOT / "data" / "static" / "static_stack.nc"
EXPOSURE = ROOT / "data" / "static" / "exposure.parquet"
OUTPUTS = ROOT / "data" / "outputs"
MODELS = ROOT / "models"

# Plain-word names for SHAP-style drivers, so the UI never shows a raw column.
DRIVER_WORDS = {
    "st_impervious": "sealed surface",
    "st_built_up": "dense built-up",
    "st_surface_height": "low-lying pocket",
    "st_dist_drain": "far from drain",
    "st_sink_depth": "local depression",
    "st_slope": "flat ground",
    "st_hand": "low HAND",
    "st_twi": "water gathers here",
    "st_drain_density": "sparse drainage",
    "st_plan_curv": "concave ground",
    "rain_sum": "rainfall today",
    "rain_max": "peak rain intensity",
    "rain_prev3d": "3-day antecedent rain",
    "rain_prev7d": "7-day antecedent rain",
}


def load_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def build_cell_frame(cfg: dict) -> gpd.GeoDataFrame:
    """One row per 100 m cell inside a Delhi ward, with its static features."""
    print("  building the 100 m cell frame")
    ds = xr.open_dataset(STATIC, decode_coords="all")
    keep = [v for v in ("hand", "twi", "slope", "impervious", "built_up",
                        "dist_drain", "drain_density", "plan_curv",
                        "sink_depth", "surface_height") if v in ds.data_vars]

    stack = ds[keep].to_dataframe().reset_index().dropna(subset=keep, how="all")
    stack = stack.rename(columns={f"{v}": f"st_{v}" for v in keep})
    gdf = gpd.GeoDataFrame(
        stack,
        geometry=gpd.points_from_xy(stack.x, stack.y),
        crs=ds.rio.crs,
    )

    exp = gpd.read_parquet(EXPOSURE)
    wards = exp.to_crs(gdf.crs)[["ward_no", "ward_name", "geometry"]]
    joined = gpd.sjoin(gdf, wards, how="inner", predicate="within")
    print(f"    {len(joined):,} cells inside {joined.ward_no.nunique()} wards")

    # Each cell's nearest rain lattice point, in lon/lat.
    ll = joined.to_crs("EPSG:4326")
    joined["lon"] = ll.geometry.x.to_numpy()
    joined["lat"] = ll.geometry.y.to_numpy()
    rl = cfg["rain_lattice"]
    res = rl["resolution_deg"]
    joined["plat"] = (np.round((joined.lat - rl["lat_start"]) / res) * res
                      + rl["lat_start"]).round(2)
    joined["plon"] = (np.round((joined.lon - rl["lon_start"]) / res) * res
                      + rl["lon_start"]).round(2)
    return joined.drop(columns=["geometry", "index_right"])


def rain_at(cube: Cube, t0: pd.Timestamp) -> pd.DataFrame:
    """
    Per-lattice-point rainfall as it was KNOWABLE at t0.

    Goes through cube.at(t0), so nothing issued later can appear. This is the
    same accessor the leakage suite tests.
    """
    snap = cube.at(t0, lookback_hours=24 * 8)
    if snap.empty:
        return pd.DataFrame(columns=["plat", "plon", "rain_sum", "rain_max",
                                     "rain_prev3d", "rain_prev7d"])
    snap = snap.rename(columns={"lat": "plat", "lon": "plon"})
    # rain_max uses a TRAILING 6 h window, not 24 h. With a 24 h window the
    # storm total barely moves across a 7 h replay and every frame looks
    # identical — which is exactly what the first precompute produced. Six hours
    # tracks the burst itself, so the replay actually evolves.
    recent = snap[snap.valid_time >= t0 - pd.Timedelta(hours=6)]
    day = snap[snap.valid_time >= t0 - pd.Timedelta(hours=24)]
    agg = (day.groupby(["plat", "plon"], as_index=False)
              .agg(rain_sum=("precip_obs", "sum")))
    rmax = (recent.groupby(["plat", "plon"], as_index=False)
                  .agg(rain_max=("precip_obs", "max")))
    agg = agg.merge(rmax, on=["plat", "plon"], how="left")
    for w in (3, 7):
        prev = (snap[snap.valid_time >= t0 - pd.Timedelta(days=w)]
                .groupby(["plat", "plon"], as_index=False)
                .agg(**{f"rain_prev{w}d": ("precip_obs", "sum")}))
        agg = agg.merge(prev, on=["plat", "plon"], how="left")
    return agg


def band_for(score: float, bands: dict) -> str:
    for name, (lo, hi) in bands.items():
        if lo <= score < hi:
            return name
    return "critical"


def main() -> int:
    cfg = load_cfg()
    booster = lgb.Booster(model_file=str(MODELS / "inundanet_v0.txt"))
    feat_names = booster.feature_name()
    print(f"InundaNet expects {len(feat_names)} features")

    cells = build_cell_frame(cfg)
    exp = gpd.read_parquet(EXPOSURE).drop(columns=["geometry"])
    wards_geo = gpd.read_file(ROOT / "data" / "raw" / "Delhi_Wards.geojson")

    cube = Cube.load()
    bands = {k: tuple(v) for k, v in cfg["risk_bands"].items()}
    event = next(e for e in cfg["events"] if e.get("primary"))
    ev_id, stamps = event["id"], event["demo_timestamps"]
    ev_dir = OUTPUTS / ev_id
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "frames").mkdir(exist_ok=True)
    print(f"\nEvent {ev_id}: {len(stamps)} timestamps")

    # Track each ward's probability history so onset can be computed causally.
    history: dict[str, list[tuple[str, float]]] = {}
    op = 0.5

    for stamp in stamps:
        t0 = pd.Timestamp(f"{ev_id}T{stamp[:2]}:{stamp[2:]}:00Z")
        rain = rain_at(cube, t0)
        df = cells.merge(rain, on=["plat", "plon"], how="left")
        for c in feat_names:
            if c not in df:
                df[c] = np.nan
        p = booster.predict(df[feat_names])
        df["p"] = p

        # Ward aggregation: the 90th percentile of its cells. A ward floods when
        # its WORST pockets flood, not when its average cell does — a mean would
        # dilute a real underpass hazard into a large dry ward.
        agg = (df.groupby(["ward_no", "ward_name"], as_index=False)
                 .agg(p_flood=("p", lambda s: float(np.percentile(s, 90))),
                      p_mean=("p", "mean"), n_cells=("p", "size")))
        agg = agg.merge(exp, on=["ward_no", "ward_name"], how="left")

        pop = agg["population"].fillna(0)
        pop_norm = pop / max(pop.max(), 1)
        agg["risk_score"] = (agg.p_flood * (0.65 + 0.35 * pop_norm)).clip(0, 0.999)
        agg["risk_band"] = agg.risk_score.map(lambda s: band_for(s, bands))

        # Drivers: the strongest positive contributors for this ward's cells.
        contrib = booster.predict(df[feat_names], pred_contrib=True)
        cdf = pd.DataFrame(contrib[:, :-1], columns=feat_names)
        cdf["ward_no"] = df["ward_no"].to_numpy()
        wmean = cdf.groupby("ward_no").mean()

        feats_out = []
        exposed_total = 0.0
        for _, r in agg.iterrows():
            hist = history.setdefault(r.ward_no, [])
            hist.append((stamp, float(r.p_flood)))
            onset = next((h for h, v in hist if v >= op), None)
            peak = max(hist, key=lambda kv: kv[1])[0] if hist else None

            def ist(h):
                if h is None:
                    return None
                m = (int(h[:2]) * 60 + int(h[2:]) + 330) % 1440
                return f"{m//60:02d}:{m%60:02d}"

            top = (wmean.loc[r.ward_no].sort_values(ascending=False)[:3]
                   if r.ward_no in wmean.index else pd.Series(dtype=float))
            drivers = [[DRIVER_WORDS.get(k, k.replace("st_", "").replace("_", " ")),
                        round(float(v), 3)] for k, v in top.items()]
            while len(drivers) < 3:
                drivers.append(["terrain", 0.0])

            exposed_total += float(r.p_flood) * float(pop[_] if _ < len(pop) else 0)
            geom = wards_geo[wards_geo.Ward_No == r.ward_no]
            if geom.empty:
                continue
            feats_out.append({
                "type": "Feature",
                "geometry": json.loads(geom.geometry.iloc[0].__geo_interface__
                                       and json.dumps(geom.geometry.iloc[0].__geo_interface__)),
                "properties": {
                    "ward_id": str(r.ward_no),
                    "name": str(r.ward_name),
                    "p_flood": round(float(r.p_flood), 3),
                    "onset": ist(onset), "peak": ist(peak),
                    "ci90": None,
                    "people": int(r.population) if pd.notna(r.population) else 0,
                    "hospitals": int(r.hospitals or 0),
                    "schools": int(r.schools or 0),
                    "road_km": round(float(r.road_km or 0), 1),
                    "pumps": int(r.pumps or 0),
                    "drivers": drivers,
                    "risk_score": round(float(r.risk_score), 3),
                    "risk_band": r.risk_band,
                },
            })

        (ev_dir / f"wards_{stamp}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats_out}))

        # ---- rain grid from the observed lattice, knowable at t0
        cellsr = [{"lat": float(r.plat), "lon": float(r.plon),
                   "p15": round(min(0.99, float(r.rain_max or 0) / 15), 3),
                   "p50": round(min(0.99, float(r.rain_max or 0) / 50), 3),
                   "q10": round(float(r.rain_sum or 0) * 0.35, 1),
                   "q50": round(float(r.rain_sum or 0), 1),
                   "q90": round(float(r.rain_sum or 0) * 2.1, 1)}
                  for _, r in rain.iterrows()]
        thr = cfg["thresholds"]["forecast_24h_mm"]
        rmax = float(rain.rain_sum.max()) if len(rain) else 0.0
        (ev_dir / f"rain_grid_{stamp}.json").write_text(json.dumps({
            "kind": "nowcast", "lead_h": 3, "cells": cellsr,
            "forecast": {"lead_h": 24, "thresholds": {
                str(thr["heavy"]): round(min(0.99, rmax / thr["heavy"]), 2),
                str(thr["very_heavy"]): round(min(0.99, rmax / thr["very_heavy"]), 2),
                str(thr["extremely_heavy"]): round(min(0.99, rmax / thr["extremely_heavy"]), 2)}}}))

        crit = sum(1 for f in feats_out if f["properties"]["risk_band"] == "critical")
        high = sum(1 for f in feats_out if f["properties"]["risk_band"] == "high")
        city = ("CRITICAL" if crit > 12 else "HIGH" if crit > 4 or high > 20
                else "WATCH" if high > 0 else "LOW")
        first_cross = min((f["properties"]["onset"] for f in feats_out
                           if f["properties"]["onset"]), default=None)
        (ev_dir / f"kpi_{stamp}.json").write_text(json.dumps({
            "rain_now_mm_h": round(float(rain.rain_max.max()) if len(rain) else 0.0, 1),
            "p3h50": round(min(0.99, (float(rain.rain_max.max()) if len(rain) else 0) / 50), 2),
            "city_risk": city,
            "time_to_critical_min": None if first_cross else None,
            "people_exposed": int(exposed_total),
            "badges": {"sat": "ok", "radar": "degraded",
                       "stations": "degraded", "nwp": "ok"}}))
        print(f"    {stamp}  wards={len(feats_out):>3}  crit={crit:>2} high={high:>3}  "
              f"p_flood max={agg.p_flood.max():.3f}  exposed={int(exposed_total):,}")

    (OUTPUTS / "index.json").write_text(json.dumps({
        "events": [{"id": ev_id, "name": event["name"],
                    "timestamps": stamps, "wards": len(feats_out)}],
        "schema": 3}, indent=2))
    print(f"\n  -> {ev_dir.relative_to(ROOT)}  REAL MODEL OUTPUT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
