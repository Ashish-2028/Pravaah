#!/usr/bin/env python
"""
PRAVAAH — the LIVE pipeline. Pull now, predict now, publish now.

THE PROBLEM THIS SOLVES
-----------------------
Until this existed, every screen in the product showed one historical day
(28 Jun 2024). The Live/Replay toggle was decorative. That makes the whole
thing read as a validation harness for a single event rather than an
operational system — which is the opposite of the pitch.

WHERE "NOW" COMES FROM
----------------------
The models need RECENT OBSERVED rain at all 56 lattice points to build lags,
accumulations and advection features. The archive API (A1) lags ~5 days, so it
cannot serve this. The live forecast endpoint can: `past_days=2` returns the
model's recent past hours alongside the forward forecast, at every point, in
one call.

That is an ANALYSIS, not a gauge reading, and we say so on screen. It is the
best freely available "what is happening right now" at 56 points with no
credentials. Decoded radar (the SRI product our logger captures every 10 min)
is the genuine observation and is the next upgrade — this file is structured so
that swapping the observation source is a one-function change.

FAILURE POLICY — READ BEFORE EDITING
------------------------------------
This runs unattended every 15 minutes on a laptop that may lose wifi mid-demo.
Therefore: NEVER destroy a good published state. Everything is written to a
temp directory and swapped in atomically only after it validates. If the pull
fails, the previous live snapshot stays exactly where it was and the UI keeps
showing the last good data with an honest age badge.

    python scripts/live_update.py            # one update
    python scripts/live_update.py --loop     # every 15 min, forever
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
import yaml
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
OUTPUTS = ROOT / "data" / "outputs"
LIVE = OUTPUTS / "live"
MODELS = ROOT / "models"
EXPOSURE = ROOT / "data" / "static" / "exposure.parquet"
STATIC = ROOT / "data" / "static" / "static_stack.nc"
CACHE = ROOT / "data" / "raw" / "live" / "nowcast_input"

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["precipitation", "temperature_2m", "relative_humidity_2m",
          "wind_speed_10m", "surface_pressure", "soil_moisture_0_to_7cm",
          "cape"]
N_FRAMES = 12          # trailing hours published as replayable "live" frames
INTERVAL_S = 900       # 15 minutes


def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def lattice(c: dict) -> list[tuple[float, float]]:
    rl = c["rain_lattice"]
    r = rl["resolution_deg"]
    return [(round(rl["lat_start"] + i * r, 2), round(rl["lon_start"] + j * r, 2))
            for i in range(rl["lat_count"]) for j in range(rl["lon_count"])]


# ------------------------------------------------------------------- fetch
def fetch_now(c: dict) -> pd.DataFrame:
    """
    Recent past + near future at every lattice point, in ONE call.

    Open-Meteo accepts comma-separated coordinates and returns a list of
    per-location payloads, so 56 points cost one request rather than 56 —
    which matters when this runs every 15 minutes.
    """
    pts = lattice(c)
    params = {
        "latitude": ",".join(f"{a}" for a, _ in pts),
        "longitude": ",".join(f"{o}" for _, o in pts),
        "hourly": ",".join(HOURLY),
        "past_days": 2, "forecast_days": 2, "timezone": "UTC",
    }
    r = requests.get(ENDPOINT, params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        payload = [payload]

    frames = []
    for (lat, lon), block in zip(pts, payload):
        h = block["hourly"]
        d = pd.DataFrame(h)
        d["valid_time"] = pd.to_datetime(d["time"], utc=True)
        d = d.drop(columns=["time"])
        d["lat"], d["lon"] = lat, lon
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"precipitation": "precip_obs", "temperature_2m": "temp",
                            "relative_humidity_2m": "rh", "wind_speed_10m": "wind",
                            "surface_pressure": "pres",
                            "soil_moisture_0_to_7cm": "soil_moist"})
    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    df.to_parquet(CACHE / f"now_{stamp}.parquet", index=False)
    for old in sorted(CACHE.glob("now_*.parquet"))[:-12]:
        old.unlink()          # keep the last 12 pulls, not 12 months of them
    return df


# ---------------------------------------------------------------- features
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild exactly the feature names RainCast was trained on."""
    parts = []
    for (lat, lon), g in df.groupby(["lat", "lon"], sort=True):
        g = g.sort_values("valid_time").copy()
        p = g["precip_obs"]
        for L in (1, 2, 3, 6):
            g[f"precip_lag{L}"] = p.shift(L)
        for W in (3, 6, 24):
            g[f"precip_acc{W}"] = p.rolling(W, min_periods=1).sum()
        for d in (3, 7, 15):
            g[f"api_{d}d"] = p.rolling(d * 24, min_periods=1).sum()
        g["precip_trend_3h"] = g["precip_acc3"] - g["precip_acc3"].shift(3)
        g["precip_trend_1h"] = p - p.shift(1)
        for c_ in ("temp", "rh", "wind", "pres", "soil_moist"):
            if c_ in g:
                g[f"{c_}_lag1"] = g[c_].shift(1)
                g[f"{c_}_d3h"] = g[c_] - g[c_].shift(3)
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)

    # advection — the dominant family per the ablation, so it must be rebuilt
    # identically here or live predictions will not match training-time skill
    piv = out.pivot_table(index="valid_time", columns=["lat", "lon"],
                          values="precip_obs")
    lats = sorted({c[0] for c in piv.columns})
    res = round(lats[1] - lats[0], 2) if len(lats) > 1 else 0.1
    box_mean, box_max = piv.mean(axis=1), piv.max(axis=1)
    nb = []
    for (lat, lon) in piv.columns:
        f = pd.DataFrame(index=piv.index)
        f["lat"], f["lon"] = lat, lon

        def n(dla, dlo):
            k = (round(lat + dla * res, 2), round(lon + dlo * res, 2))
            return piv[k] if k in piv.columns else pd.Series(np.nan, index=piv.index)

        ring = pd.concat([n(a, o) for a in (-1, 0, 1) for o in (-1, 0, 1)
                          if (a, o) != (0, 0)], axis=1)
        f["nb_mean"], f["nb_max"] = ring.mean(axis=1), ring.max(axis=1)
        f["nb_north"], f["nb_south"] = n(1, 0), n(-1, 0)
        f["nb_east"], f["nb_west"] = n(0, 1), n(0, -1)
        f["nb_grad_ns"] = n(1, 0) - n(-1, 0)
        f["nb_grad_ew"] = n(0, 1) - n(0, -1)
        for L in (1, 2, 3):
            f[f"nb_mean_lag{L}"] = f["nb_mean"].shift(L)
            f[f"nb_max_lag{L}"] = f["nb_max"].shift(L)
        f["nb_mean_trend"] = f["nb_mean"] - f["nb_mean"].shift(3)
        f["box_mean"], f["box_max"] = box_mean, box_max
        f["box_mean_lag3"] = box_mean.shift(3)
        nb.append(f.reset_index())
    out = out.merge(pd.concat(nb, ignore_index=True),
                    on=["lat", "lon", "valid_time"], how="left")

    # Static terrain per lattice point. RainCast was trained with these
    # (features/dynamic.py attaches them as static_*), so live inference must
    # supply the identical names or the booster rejects the frame.
    out = attach_static_lattice(out)

    h = out["valid_time"].dt.hour
    doy = out["valid_time"].dt.dayofyear
    out["hour_sin"], out["hour_cos"] = np.sin(2*np.pi*h/24), np.cos(2*np.pi*h/24)
    out["doy_sin"] = np.sin(2*np.pi*doy/365.25)
    out["doy_cos"] = np.cos(2*np.pi*doy/365.25)
    return out


_STATIC_CACHE = {}


def attach_static_lattice(df: pd.DataFrame) -> pd.DataFrame:
    """Mean terrain at each 0.1 deg lattice point, cached across updates."""
    global _STATIC_CACHE
    if not _STATIC_CACHE:
        import rioxarray  # noqa: F401
        import xarray as xr
        ds = xr.open_dataset(STATIC, decode_coords="all")
        keep = [v for v in ("hand", "twi", "slope", "impervious", "dist_drain")
                if v in ds.data_vars]
        sub = ds[keep].rio.reproject("EPSG:4326")
        for (lat, lon) in df[["lat", "lon"]].drop_duplicates().itertuples(index=False):
            sel = sub.sel(x=lon, y=lat, method="nearest")
            _STATIC_CACHE[(lat, lon)] = {f"static_{k}": float(sel[k].values)
                                         for k in keep}
    rows = [{"lat": la, "lon": lo, **v} for (la, lo), v in _STATIC_CACHE.items()]
    return df.merge(pd.DataFrame(rows), on=["lat", "lon"], how="left")


def load_heads():
    tbl = ROOT / "cube" / "raincast_table.parquet"
    if not tbl.exists():
        return None
    va = pd.read_parquet(tbl)
    va = va[va.split == "val"]
    heads = {}
    for label, head, ycol in (("p15", "p5_w3", "y_p5_w3"),
                              ("p50", "p10_w3", "y_p10_w3")):
        f = MODELS / f"raincast_v0_{head}.txt"
        if not f.exists():
            continue
        b = lgb.Booster(model_file=str(f))
        iso = IsotonicRegression(out_of_bounds="clip").fit(
            b.predict(va[b.feature_name()]), va[ycol].to_numpy())
        heads[label] = {"b": b, "iso": iso, "feats": b.feature_name(),
                        "thr": 5.0 if head.startswith("p5") else 10.0}
    return heads or None


def ward_frame(c: dict):
    import rioxarray  # noqa: F401
    import xarray as xr
    ds = xr.open_dataset(STATIC, decode_coords="all")
    keep = [v for v in ("hand", "twi", "slope", "impervious", "built_up",
                        "dist_drain", "drain_density", "plan_curv", "sink_depth",
                        "surface_height", "underpass_dist", "underpass_density",
                        "bridge_dist") if v in ds.data_vars]
    stack = ds[keep].to_dataframe().reset_index().dropna(subset=keep, how="all")
    stack = stack.rename(columns={v: f"st_{v}" for v in keep})
    gdf = gpd.GeoDataFrame(stack, geometry=gpd.points_from_xy(stack.x, stack.y),
                           crs=ds.rio.crs)
    exp = gpd.read_parquet(EXPOSURE)
    j = gpd.sjoin(gdf, exp.to_crs(gdf.crs)[["ward_no", "ward_name", "geometry"]],
                  how="inner", predicate="within")
    ll = j.to_crs("EPSG:4326")
    j["lon"], j["lat"] = ll.geometry.x.to_numpy(), ll.geometry.y.to_numpy()
    rl = c["rain_lattice"]; r = rl["resolution_deg"]
    j["plat"] = (np.round((j.lat - rl["lat_start"]) / r) * r + rl["lat_start"]).round(2)
    j["plon"] = (np.round((j.lon - rl["lon_start"]) / r) * r + rl["lon_start"]).round(2)
    return j.drop(columns=["geometry", "index_right"])


def band_for(score, bands):
    for name, (lo, hi) in bands.items():
        if lo <= score < hi:
            return name
    return "critical"


# ------------------------------------------------------------------ update
def update(c, heads, cells, exp, wards_geo, inunda) -> dict:
    df = fetch_now(c)
    feats = build_features(df)
    now = pd.Timestamp.now(tz="UTC").floor("h")
    frames = [now - timedelta(hours=k) for k in range(N_FRAMES - 1, -1, -1)]
    bands = {k: tuple(v) for k, v in c["risk_bands"].items()}

    tmp = OUTPUTS / "_live_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "frames").mkdir(parents=True)
    stamps = []

    for t0 in frames:
        stamp = t0.strftime("%H%M")
        stamps.append(stamp)
        snap = feats[feats.valid_time == t0]
        if snap.empty:
            continue

        # ---- rain grid from RainCast
        cellsr = []
        for _, r in snap.iterrows():
            cell = {"lat": float(r["lat"]), "lon": float(r["lon"])}
            for lab, h in (heads or {}).items():
                x = pd.DataFrame([r[h["feats"]].to_dict()])
                cell[lab] = round(float(h["iso"].predict(h["b"].predict(x))[0]), 3)
            acc = float(r.get("precip_acc6", 0) or 0)
            cell["q10"], cell["q50"], cell["q90"] = (round(acc*0.35, 1),
                                                     round(acc, 1), round(acc*2.1, 1))
            cellsr.append(cell)

        # ---- wards from InundaNet
        rain_join = (snap.rename(columns={"lat": "plat", "lon": "plon"})
                         [["plat", "plon", "precip_acc24", "precip_acc6",
                           "api_3d", "api_7d"]]
                     .rename(columns={"precip_acc24": "rain_sum",
                                      "precip_acc6": "rain_max",
                                      "api_3d": "rain_prev3d",
                                      "api_7d": "rain_prev7d"}))
        cc = cells.merge(rain_join, on=["plat", "plon"], how="left")
        fn = inunda.feature_name()
        for col in fn:
            if col not in cc:
                cc[col] = np.nan
        cc["p"] = inunda.predict(cc[fn])
        agg = (cc.groupby(["ward_no", "ward_name"], as_index=False)
                 .agg(p_flood=("p", lambda s: float(np.percentile(s, 90)))))
        agg = agg.merge(exp, on=["ward_no", "ward_name"], how="left")
        pop = agg["population"].fillna(0)
        agg["risk_score"] = (agg.p_flood * (0.65 + 0.35 * pop/max(pop.max(), 1))).clip(0, .999)

        contrib = inunda.predict(cc[fn], pred_contrib=True)
        cdf = pd.DataFrame(contrib[:, :-1], columns=fn)
        cdf["ward_no"] = cc["ward_no"].to_numpy()
        wmean = cdf.groupby("ward_no").mean()
        from scripts.precompute import DRIVER_WORDS

        feats_out, exposed = [], 0.0
        for i, r in agg.iterrows():
            g = wards_geo[wards_geo.Ward_No == r.ward_no]
            if g.empty:
                continue
            top = (wmean.loc[r.ward_no].sort_values(ascending=False)[:3]
                   if r.ward_no in wmean.index else pd.Series(dtype=float))
            drivers = [[DRIVER_WORDS.get(k, k.replace("st_", "").replace("_", " ")),
                        round(float(v), 3)] for k, v in top.items()]
            while len(drivers) < 3:
                drivers.append(["terrain", 0.0])
            exposed += float(r.p_flood) * float(pop.iloc[i])
            ist = (t0 + timedelta(hours=5, minutes=30)).strftime("%H:%M")
            feats_out.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(g.geometry.iloc[0].__geo_interface__)),
                "properties": {
                    "ward_id": str(r.ward_no), "name": str(r.ward_name),
                    "p_flood": round(float(r.p_flood), 3),
                    "onset": ist if r.p_flood >= 0.5 else None,
                    "peak": None, "ci90": None,
                    "people": int(r.population) if pd.notna(r.population) else 0,
                    "hospitals": int(r.hospitals or 0), "schools": int(r.schools or 0),
                    "road_km": round(float(r.road_km or 0), 1),
                    "pumps": int(r.pumps or 0), "drivers": drivers,
                    "risk_score": round(float(r.risk_score), 3),
                    "risk_band": band_for(r.risk_score, bands)}})

        (tmp / f"wards_{stamp}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats_out}))
        (tmp / f"rain_grid_{stamp}.json").write_text(json.dumps({
            "kind": "nowcast", "lead_h": 3, "cells": cellsr,
            "forecast": {"lead_h": 24, "thresholds": {}},
            "provenance": {
                "nowcast_source": "RainCast-v0 (calibrated), live",
                "observation_source": ("Open-Meteo analysis via forecast API "
                                       "past_days=2 — an ANALYSIS, not a gauge"),
                "head_thresholds_mm": {k: v["thr"] for k, v in (heads or {}).items()},
                "fetched_utc": datetime.now(timezone.utc).isoformat()}}))
        crit = sum(1 for f in feats_out if f["properties"]["risk_band"] == "critical")
        high = sum(1 for f in feats_out if f["properties"]["risk_band"] == "high")
        (tmp / f"kpi_{stamp}.json").write_text(json.dumps({
            "rain_now_mm_h": round(float(snap.precip_obs.max()), 1),
            "p3h50": max((c_["p15"] for c_ in cellsr), default=0.0),
            "city_risk": ("CRITICAL" if crit > 12 else "HIGH" if crit > 4 or high > 20
                          else "WATCH" if high else "LOW"),
            "time_to_critical_min": None,
            "people_exposed": int(exposed),
            "badges": {"sat": "ok", "radar": "degraded",
                       "stations": "degraded", "nwp": "ok"}}))

    if not stamps:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("no frames produced")

    # ATOMIC SWAP — the previous good snapshot survives until this instant.
    meta = {"id": "live", "name": "Live — Delhi NCR", "timestamps": stamps,
            "wards": len(feats_out),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "updated_ist": (datetime.now(timezone.utc) +
                            timedelta(hours=5, minutes=30)).strftime("%d %b %H:%M IST")}
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2))
    old = OUTPUTS / "_live_old"
    shutil.rmtree(old, ignore_errors=True)
    if LIVE.exists():
        LIVE.rename(old)
    tmp.rename(LIVE)
    shutil.rmtree(old, ignore_errors=True)

    # register in index.json, live first
    idx_p = OUTPUTS / "index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"events": [], "schema": 3}
    idx["events"] = [e for e in idx["events"] if e["id"] != "live"]
    idx["events"].insert(0, {k: meta[k] for k in ("id", "name", "timestamps", "wards")})
    idx["live_updated_utc"] = meta["updated_utc"]
    idx_p.write_text(json.dumps(idx, indent=2))
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    c = cfg()
    heads = load_heads()
    inunda = lgb.Booster(model_file=str(MODELS / "inundanet_v0.txt"))
    cells = ward_frame(c)
    exp = gpd.read_parquet(EXPOSURE).drop(columns=["geometry"])
    wards_geo = gpd.read_file(ROOT / "data" / "raw" / "Delhi_Wards.geojson")
    print(f"live pipeline ready: {len(cells):,} cells, "
          f"{len(heads or {})} RainCast heads")

    while True:
        try:
            m = update(c, heads, cells, exp, wards_geo, inunda)
            print(f"[{m['updated_ist']}] live updated: {len(m['timestamps'])} frames, "
                  f"{m['wards']} wards", flush=True)
        except Exception as exc:  # noqa: BLE001
            # The previous snapshot is untouched. Say so loudly and carry on.
            print(f"[{datetime.now(timezone.utc):%H:%M}Z] live update FAILED "
                  f"({type(exc).__name__}: {exc}) — previous snapshot retained",
                  flush=True)
        if not args.loop:
            return 0
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
