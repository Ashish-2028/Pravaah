#!/usr/bin/env python
"""
PRAVAAH — IMERG features for RainCast (A4 integration).

WHY THIS SHOULD HELP, MECHANISTICALLY
-------------------------------------
RainCast's dominant signal is ADVECTION — where existing rain is drifting (the
ablation put it at -0.040 CSI when removed, the largest of any family). Advection
is estimated from how the rain field MOVES between consecutive frames, so the
frame rate is the binding constraint:

    ERA5   1 frame / hour     a storm crossing at 40 km/h moves ~40 km per frame
    IMERG  1 frame / 30 min   the same storm moves ~20 km per frame

At an 11 km lattice spacing, hourly frames badly undersample the motion. Halving
the interval is a direct upgrade to the one family that matters most.

Second reason, measured on the demo event: IMERG PEAKS EARLIER than ERA5
(00:00Z vs 01:00Z on 28 Jun 2024). A satellite observation that leads the
reanalysis by an hour is worth real lead time in a 0-6 h product.

WHAT THIS IS NOT
----------------
IMERG is a satellite RETRIEVAL and understates convective peaks — 32.9 mm
accumulated for an event the gauge network put at 150.7 mm (PRAVAAH.md §5.6).
It is used here strictly as a PREDICTOR of storm structure and motion, never as
a truth label. The target stays ERA5-derived; IMD gridded stays the exceedance
truth.

    python features/imerg_features.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

IMERG = ROOT / "data" / "raw" / "imerg"
TABLE = ROOT / "cube" / "raincast_table.parquet"
OUT = ROOT / "cube" / "raincast_table_imerg.parquet"


def load_imerg() -> pd.DataFrame:
    files = sorted(glob.glob(str(IMERG / "*.parquet")))
    if not files:
        raise FileNotFoundError("no IMERG files — run ingest/imerg_gee.py")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["valid_time"] = pd.to_datetime(df["valid_time"], utc=True)
    print(f"  IMERG {len(df):,} rows, {df.groupby(['lat','lon']).ngroups} cells, "
          f"{df.valid_time.min().date()} .. {df.valid_time.max().date()}")
    return df


def snap_to_lattice(imerg: pd.DataFrame, lattice: pd.DataFrame) -> pd.DataFrame:
    """
    IMERG's grid is offset from ours by a fraction of a cell, so join each
    IMERG cell to its nearest lattice point rather than assuming they coincide.
    """
    ipts = imerg[["lat", "lon"]].drop_duplicates().to_numpy()
    lpts = lattice[["lat", "lon"]].drop_duplicates().to_numpy()
    rows = []
    for ila, ilo in ipts:
        d = (lpts[:, 0] - ila) ** 2 + (lpts[:, 1] - ilo) ** 2
        p = lpts[int(d.argmin())]
        rows.append({"lat": ila, "lon": ilo,
                     "plat": float(p[0]), "plon": float(p[1])})
    xw = pd.DataFrame(rows)
    print(f"  snapped {len(ipts)} IMERG cells -> {xw.plat.nunique()*xw.plon.nunique()} "
          f"lattice positions")
    return imerg.merge(xw, on=["lat", "lon"], how="left")


def build(imerg: pd.DataFrame) -> pd.DataFrame:
    """Per lattice point per HOUR, features derived from 30-minute frames."""
    g = imerg.groupby(["plat", "plon", "valid_time"], as_index=False)[
        "imerg_mm_hr"].mean()
    g["hour"] = g["valid_time"].dt.floor("h")
    g["half"] = (g["valid_time"].dt.minute >= 30).astype(int)

    # Hourly aggregate + the SUB-HOURLY structure that ERA5 cannot express.
    hourly = (g.groupby(["plat", "plon", "hour"], as_index=False)
                .agg(im_mean=("imerg_mm_hr", "mean"),
                     im_max=("imerg_mm_hr", "max"),
                     im_n=("imerg_mm_hr", "size")))
    halves = (g.pivot_table(index=["plat", "plon", "hour"], columns="half",
                            values="imerg_mm_hr", aggfunc="mean")
                .rename(columns={0: "im_h1", 1: "im_h2"}).reset_index())
    out = hourly.merge(halves, on=["plat", "plon", "hour"], how="left")
    # Intra-hour tendency: rising or falling WITHIN the hour. This is the piece
    # of information an hourly product structurally cannot carry.
    out["im_half_trend"] = out.get("im_h2", 0) - out.get("im_h1", 0)

    parts = []
    for (la, lo), sub in out.groupby(["plat", "plon"]):
        sub = sub.sort_values("hour").copy()
        s = sub["im_mean"]
        for L in (1, 2, 3, 6):
            sub[f"im_lag{L}"] = s.shift(L)
        for W in (3, 6, 24):
            sub[f"im_acc{W}"] = s.rolling(W, min_periods=1).sum()
        sub["im_trend_1h"] = s - s.shift(1)
        sub["im_trend_3h"] = sub["im_acc3"] - sub["im_acc3"].shift(3)
        parts.append(sub)
    out = pd.concat(parts, ignore_index=True)

    # ---- ADVECTION at IMERG resolution: the whole point of this file.
    piv = out.pivot_table(index="hour", columns=["plat", "plon"],
                          values="im_mean")
    lats = sorted({c[0] for c in piv.columns})
    res = round(lats[1] - lats[0], 2) if len(lats) > 1 else 0.1
    frames = []
    for (la, lo) in piv.columns:
        f = pd.DataFrame(index=piv.index)
        f["plat"], f["plon"] = la, lo

        def nb(dla, dlo):
            k = (round(la + dla * res, 2), round(lo + dlo * res, 2))
            return piv[k] if k in piv.columns else pd.Series(np.nan, index=piv.index)

        ring = [nb(a, o) for a in (-1, 0, 1) for o in (-1, 0, 1) if (a, o) != (0, 0)]
        rdf = pd.concat(ring, axis=1)
        f["im_nb_mean"] = rdf.mean(axis=1)
        f["im_nb_max"] = rdf.max(axis=1)
        f["im_grad_ns"] = nb(1, 0) - nb(-1, 0)
        f["im_grad_ew"] = nb(0, 1) - nb(0, -1)
        for L in (1, 2, 3):
            f[f"im_nb_mean_lag{L}"] = f["im_nb_mean"].shift(L)
        f["im_box_mean"] = piv.mean(axis=1)
        f["im_box_max"] = piv.max(axis=1)
        frames.append(f.reset_index())
    nbf = pd.concat(frames, ignore_index=True)
    out = out.merge(nbf, on=["plat", "plon", "hour"], how="left")
    print(f"  built {len(out):,} point-hours, "
          f"{len([c for c in out.columns if c.startswith('im_')])} IMERG features")
    return out


def main() -> int:
    if not TABLE.exists():
        print("run features/dynamic.py first")
        return 1
    base = pd.read_parquet(TABLE)
    print(f"  base table {len(base):,} rows")

    imerg = load_imerg()
    imerg = snap_to_lattice(imerg, base[["lat", "lon"]].drop_duplicates())
    feats = build(imerg)

    base["hour"] = base["valid_time"].dt.floor("h")
    merged = base.merge(
        feats.rename(columns={"plat": "lat", "plon": "lon"}),
        on=["lat", "lon", "hour"], how="left").drop(columns=["hour"])

    imcols = [c for c in merged.columns if c.startswith("im_")]
    cov = merged[imcols].notna().mean().mean()
    print(f"  merged: {len(merged):,} rows, {len(imcols)} IMERG columns, "
          f"mean coverage {cov:.1%}")
    tr = merged[merged.split == "train"]
    print(f"  train coverage of im_mean: {tr['im_mean'].notna().mean():.1%}")

    merged.to_parquet(OUT, index=False)
    print(f"  -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
