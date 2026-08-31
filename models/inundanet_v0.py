#!/usr/bin/env python
"""
PRAVAAH — InundaNet-v0, rain -> water on the ground (BUILD_PLAN P6).

WHAT IT SHOULD LEARN
--------------------
The interaction a threshold rule cannot express: 50 mm on a low-HAND,
high-impervious cell far from a drain with saturated soil floods; the same
50 mm two streets uphill does not.

WHAT WE ALREADY KNOW BEFORE TRAINING — AND MUST NOT PRETEND AWAY
----------------------------------------------------------------
Two independent measurements say the static terrain map does NOT explain where
Delhi actually floods:

  1. Phase 2 gate: of six known waterlogging wards, ONE (Minto Road, 85.9 pct)
     lands in the top quintile of terrain susceptibility. Jama Masjid is at
     3.1 pct and Turkman Gate at 7.6 pct while being 92% and 100% impervious —
     because HAND reads 14.9 m and 14.3 m there.
  2. Label audit: top_quintile_enrichment = 0.94, i.e. labelled flood points sit
     in high-susceptibility cells very slightly LESS often than random cells.

So the honest prior is: this model can learn WHEN (event level, driven by rain)
much more easily than WHERE (cell level, driven by terrain). The evaluation
below is built to EXPOSE that distinction rather than hide it, because a single
pooled AUC-PR would look respectable purely from the rain signal while the
cell-level ranking — the thing the product actually claims — could be near
random.

METHODOLOGY GUARDS
------------------
* lat / lon / x_utm / y_utm / cell_id / row / col ARE EXCLUDED as features.
  With 84 labelled points and negatives sampled >1 km away, raw coordinates let
  a tree memorise "near a known blackspot" and score beautifully while learning
  nothing transferable. This is the single easiest way to fake this model.
* SPATIAL-BLOCK CV on 5 km blocks (charter R5). Adjacent 100 m cells are near
  duplicates; a random split would put a cell's own neighbours in train.
* Baseline = HAND alone. HAND is already a strong flood predictor, so the model
  must beat it or it has added nothing.
* A separate EVENT-LEVEL and CELL-LEVEL score, reported side by side.

    python models/inundanet_v0.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
LABELS = (ROOT / "data" / "labels" / "inunda_labels_v2.parquet"
          if (ROOT / "data" / "labels" / "inunda_labels_v2.parquet").exists()
          else ROOT / "data" / "labels" / "inunda_labels.parquet")
STATIC = ROOT / "data" / "static" / "static_stack.nc"
CUBE = ROOT / "cube" / "ncr_cube.parquet"
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"

# NEVER features — these encode WHERE a cell is, and with 84 labelled points
# that is equivalent to handing the model the answer key.
FORBIDDEN = {
    # --- geography: with 84 labelled points, coordinates ARE the answer key
    "cell_id", "lat", "lon", "x_utm", "y_utm", "row", "col", "block_id",
    # --- bookkeeping
    "label", "event_id", "confidence", "source", "event_start", "event_end",
    "event_origin", "holdout",
    # --- LABEL-PROCESS LEAKAGE. Every one of these is computed DURING labelling
    # and is therefore a function of the answer. Caught the hard way: the first
    # run scored AUC-PR 0.91 / within-event ROC-AUC 0.965, which was impossible
    # given that two independent measurements had already shown terrain does not
    # explain these labels. `point_rain_mm` was the top feature by 2x. Checking
    # the columns against the label:
    #     point_id / point_name  100% null for negatives, 0% null for positives
    #     sample_weight          exactly 1.0 for negatives, 0.637 for positives
    #     rain_confirmed         0.878 vs 0.574
    #     point_rain_mm          97.4 vs 69.9
    # Any of these lets a tree read the label straight off. point_id/point_name
    # were excluded only by accident (they are strings and the numeric filter
    # dropped them) — luck is not a methodology, so they are named here.
    "point_id", "point_name", "point_rain_mm", "rain_confirmed", "sample_weight",
}


def attach_static(df: pd.DataFrame) -> pd.DataFrame:
    """Sample the 100 m static stack at each labelled cell."""
    import rioxarray  # noqa: F401
    import xarray as xr

    ds = xr.open_dataset(STATIC, decode_coords="all")
    keep = [v for v in ("hand", "twi", "slope", "impervious", "built_up",
                        "dist_drain", "drain_density", "plan_curv",
                        "sink_depth", "acc", "surface_height",
                        # OSM grade-separation: the closest thing to open
                        # drainage data that exists (see ingest/osm_underpass.py)
                        "underpass_dist", "underpass_density", "bridge_dist")
            if v in ds.data_vars]
    print(f"  static layers: {keep}")

    xs = xr.DataArray(df["x_utm"].to_numpy(), dims="pt")
    ys = xr.DataArray(df["y_utm"].to_numpy(), dims="pt")
    for v in keep:
        try:
            df[f"st_{v}"] = ds[v].sel(x=xs, y=ys, method="nearest").values
        except Exception as exc:  # noqa: BLE001
            print(f"    ! {v} skipped ({type(exc).__name__})")
    return df


def attach_rain(df: pd.DataFrame) -> pd.DataFrame:
    """
    Event rainfall from the cube, at the nearest 0.1 deg lattice point.

    NOTE, AND SAY THIS OUT LOUD: rain is constant across a whole 0.1 deg (~11 km)
    lattice cell. So rain can separate EVENTS from each other, but it cannot
    separate one 100 m cell from its neighbour inside the same event. Everything
    that discriminates WITHIN an event has to come from the static terrain — and
    the label audit says the static terrain does not correlate with the labels.
    That tension is the core finding of this model, not a bug in it.
    """
    cube = pd.read_parquet(CUBE, columns=["lat", "lon", "valid_time", "precip_obs"])
    cube["date"] = cube["valid_time"].dt.tz_convert("UTC").dt.normalize()
    daily = (cube.groupby(["lat", "lon", "date"], as_index=False)
                 .agg(rain_sum=("precip_obs", "sum"),
                      rain_max=("precip_obs", "max")))

    pts = daily[["lat", "lon"]].drop_duplicates().to_numpy()
    cells = df[["lat", "lon"]].drop_duplicates()
    xw = []
    for la, lo in cells.to_numpy():
        d = (pts[:, 0] - la) ** 2 + (pts[:, 1] - lo) ** 2
        p = pts[int(d.argmin())]
        xw.append({"lat": la, "lon": lo, "plat": float(p[0]), "plon": float(p[1])})
    df = df.merge(pd.DataFrame(xw), on=["lat", "lon"], how="left")

    df["date"] = pd.to_datetime(df["event_start"]).dt.tz_localize("UTC").dt.normalize()
    d2 = daily.rename(columns={"lat": "plat", "lon": "plon"})
    df = df.merge(d2, on=["plat", "plon", "date"], how="left")

    # Antecedent rain: the 3 and 7 days before the event.
    for w in (3, 7):
        prev = d2.copy()
        prev["date"] = prev["date"] + pd.Timedelta(days=w)
        df = df.merge(prev[["plat", "plon", "date", "rain_sum"]]
                        .rename(columns={"rain_sum": f"rain_prev{w}d"}),
                      on=["plat", "plon", "date"], how="left")
    return df.drop(columns=["plat", "plon", "date"])


def main() -> int:
    if not LABELS.exists():
        print("labels missing — run the label pipeline first")
        return 1
    df = pd.read_parquet(LABELS)
    print(f"InundaNet-v0   {len(df):,} labelled cell-events, "
          f"{int(df.label.sum()):,} positive")

    df = attach_static(df)
    df = attach_rain(df)

    feats = [c for c in df.columns
             if c not in FORBIDDEN and pd.api.types.is_numeric_dtype(df[c])]
    print(f"  {len(feats)} features (coordinates + label-process cols excluded)")
    print(f"    {feats}")
    # Tripwire: no surviving feature may separate the classes almost perfectly.
    # If one does, it is leakage, not signal.
    for c in feats:
        a, b_ = df.loc[df.label == 1, c], df.loc[df.label == 0, c]
        if a.notna().mean() < 0.02 or b_.notna().mean() < 0.02:
            print(f"    !! LEAK SUSPECT {c}: null-rate differs by class")
    X, y = df[feats], df["label"].to_numpy()
    groups = df["block_id"].to_numpy()
    w = df["sample_weight"].to_numpy() if "sample_weight" in df else None

    # ---------------------------------------------------- BASELINE: HAND alone
    # Lower HAND = more flood-prone, so negate it to make it a "score".
    if "st_hand" in df:
        h = -df["st_hand"].fillna(df["st_hand"].median()).to_numpy()
        base_ap = average_precision_score(y, h)
        base_auc = roc_auc_score(y, h)
    else:
        base_ap = base_auc = float("nan")
    prevalence = float(y.mean())
    print(f"\n  base rate {prevalence:.4f}")
    print(f"  BASELINE HAND-only     AUC-PR {base_ap:.4f}   ROC-AUC {base_auc:.4f}")

    # -------------------------------------------- SPATIAL-BLOCK CV (charter R5)
    n_blocks = len(np.unique(groups))
    n_splits = min(5, n_blocks)
    gkf = GroupKFold(n_splits=n_splits)
    oof = np.zeros(len(df))
    # MONOTONIC CONSTRAINT ON RAIN. Physically, more rain can never make a cell
    # LESS likely to flood — but the unconstrained model learned a wobbly,
    # non-monotonic response (p dipped between 50 and 80 mm), which made the
    # replay show flood risk FALLING as the cloudburst peaked. That is
    # indefensible on screen regardless of what the CV score says.
    # +1 forces the response to be non-decreasing in each rain feature; terrain
    # features stay unconstrained (0) because their effect genuinely can go
    # either way.
    mono = [1 if c.startswith("rain") else 0 for c in feats]
    params = dict(objective="binary", learning_rate=0.05, num_leaves=31,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                  min_data_in_leaf=100, verbose=-1,
                  monotone_constraints=mono)
    booster = None
    for k, (tr, va) in enumerate(gkf.split(X, y, groups), 1):
        ds = lgb.Dataset(X.iloc[tr], y[tr], weight=None if w is None else w[tr])
        dv = lgb.Dataset(X.iloc[va], y[va], reference=ds)
        booster = lgb.train(params, ds, 400, valid_sets=[dv],
                            callbacks=[lgb.early_stopping(40, verbose=False)])
        oof[va] = booster.predict(X.iloc[va], num_iteration=booster.best_iteration)
        print(f"    fold {k}/{n_splits}  train {len(tr):,}  val {len(va):,}")

    # ------------------------------------------------ NEGATIVE SAMPLING BIAS
    # THE MOST IMPORTANT CHECK IN THIS FILE.
    #
    # Negatives were drawn >1 km from any positive. In Delhi's geography that
    # mostly means OUTSIDE the dense core, so the two classes differ in a way
    # that has nothing to do with flooding:
    #
    #     impervious   positives 0.827   negatives 0.244
    #     built_up     positives 0.378   negatives 0.105
    #
    # and `impervious` ALONE scores ROC-AUC 0.867 as a classifier. A model can
    # therefore look excellent while having learned only "is this cell urban".
    # That is the classic presence-only sampling artifact, and reporting the
    # unmatched number as flood skill would be the most misleading thing in
    # this whole project.
    #
    # So we re-score on IMPERVIOUSNESS-MATCHED negatives: for each positive,
    # keep only negatives in the same imperviousness band. The urban/rural
    # shortcut is removed and whatever skill survives is about hydrology.
    matched_ap = matched_auc = float("nan")
    n_matched = 0
    if "st_impervious" in df:
        imp = df["st_impervious"].fillna(df["st_impervious"].median())
        bands = pd.cut(imp, bins=[-0.01, 0.2, 0.4, 0.6, 0.8, 1.01], labels=False)
        keep_idx = []
        rng = np.random.default_rng(20240628)
        for band in np.unique(bands.dropna()):
            m = bands == band
            pos_i = np.where(m & (y == 1))[0]
            neg_i = np.where(m & (y == 0))[0]
            if len(pos_i) == 0 or len(neg_i) == 0:
                continue
            # cap negatives at 10x positives WITHIN the band
            take = min(len(neg_i), len(pos_i) * 10)
            keep_idx += list(pos_i) + list(rng.choice(neg_i, take, replace=False))
        if keep_idx:
            k = np.array(sorted(set(keep_idx)))
            n_matched = len(k)
            if len(np.unique(y[k])) > 1:
                matched_ap = average_precision_score(y[k], oof[k])
                matched_auc = roc_auc_score(y[k], oof[k])
                imp_only_auc = roc_auc_score(y[k], imp.to_numpy()[k])
                print(f"\n  MATCHED-NEGATIVE re-score ({n_matched:,} rows, "
                      f"base rate {y[k].mean():.4f})")
                print(f"    AUC-PR {matched_ap:.4f}   ROC-AUC {matched_auc:.4f}")
                print(f"    imperviousness alone on the same rows: "
                      f"ROC-AUC {imp_only_auc:.4f}")

    model_ap = average_precision_score(y, oof)
    model_auc = roc_auc_score(y, oof)
    print(f"\n  MODEL (spatial-block CV) AUC-PR {model_ap:.4f}   "
          f"ROC-AUC {model_auc:.4f}")
    print(f"  lift over base rate      {model_ap / prevalence:.2f}x")
    print(f"  lift over HAND baseline  {model_ap / base_ap:.2f}x")

    # ------------------------------- THE DECOMPOSITION THAT MATTERS: WHERE vs WHEN
    # WITHIN-EVENT ranking is the product's actual claim ("these wards, this
    # event"). Score each event separately and average — if this is ~0.5 the
    # model cannot tell cells apart and we must say so plainly.
    within = []
    for ev, g in df.assign(p=oof).groupby("event_id"):
        if g.label.nunique() < 2 or len(g) < 50:
            continue
        within.append(roc_auc_score(g.label, g.p))
    within_auc = float(np.mean(within)) if within else float("nan")

    # BETWEEN-EVENT: can it tell a flood day from a quiet day at all?
    ev_agg = df.assign(p=oof).groupby("event_id").agg(
        p=("p", "mean"), lab=("label", "mean"))
    between_auc = (roc_auc_score((ev_agg.lab > ev_agg.lab.median()).astype(int),
                                 ev_agg.p)
                   if ev_agg.lab.nunique() > 1 else float("nan"))

    print(f"\n  WITHIN-EVENT  ROC-AUC {within_auc:.4f}   "
          f"<- can it rank CELLS?  (0.5 = no)")
    print(f"  BETWEEN-EVENT ROC-AUC {between_auc:.4f}   "
          f"<- can it rank EVENTS? ({len(ev_agg)} events)")

    imp = sorted(zip(feats, booster.feature_importance("gain")), key=lambda kv: -kv[1])[:10]
    print("\n  top features by gain:")
    for k, v in imp:
        print(f"    {k:<24} {v:,.0f}")

    MODELS.mkdir(exist_ok=True)
    booster.save_model(str(MODELS / "inundanet_v0.txt"))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "inundanet_metrics.json").write_text(json.dumps({
        "n_rows": int(len(df)), "n_positive": int(y.sum()),
        "base_rate": prevalence, "n_spatial_blocks": int(n_blocks),
        "cv": f"GroupKFold {n_splits}-fold on 5 km spatial blocks",
        "model": {"auc_pr": round(model_ap, 4), "roc_auc": round(model_auc, 4)},
        "baseline_hand_only": {"auc_pr": round(float(base_ap), 4),
                               "roc_auc": round(float(base_auc), 4)},
        "lift_over_hand": round(float(model_ap / base_ap), 3),
        "within_event_roc_auc": round(within_auc, 4),
        "matched_negatives": {
            "n_rows": int(n_matched),
            "auc_pr": None if np.isnan(matched_ap) else round(float(matched_ap), 4),
            "roc_auc": None if np.isnan(matched_auc) else round(float(matched_auc), 4),
            "why": ("Negatives sampled >1 km from positives are systematically "
                    "less urban (impervious 0.24 vs 0.83), so imperviousness "
                    "alone scores ROC-AUC 0.867. Re-scoring on imperviousness-"
                    "matched negatives removes that shortcut; what survives is "
                    "hydrological skill rather than an urban/rural artifact."),
        },
        "between_event_roc_auc": round(float(between_auc), 4),
        "top_features": [{"feature": k, "gain": float(v)} for k, v in imp],
        "honesty_note": (
            "WITHIN-EVENT AUC is the number that matters for the product's "
            "ward-ranking claim. Coordinates were excluded as features to "
            "prevent memorising the 84 label locations. Two independent "
            "measurements (Phase 2 gate, label enrichment 0.94) already showed "
            "static terrain does not explain where Delhi floods."),
    }, indent=2))
    print("\n  -> reports/inundanet_metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
