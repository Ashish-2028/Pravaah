#!/usr/bin/env python
"""
PRAVAAH — RainCast-v0, the 0-6 h nowcast (BUILD_PLAN P5).

WHAT IT LEARNS
--------------
Persistence-with-correction. Rain that has been intensifying for two hours
under high CAPE usually keeps going; RainCast learns WHEN to trust that
extrapolation and when the atmosphere says otherwise.

THE EXIT GATE (charter §7.1)
----------------------------
    CSI(RainCast) > CSI(persistence)  AND  > CSI(raw NWP)   on the TEST year.
    If not met: ADD FEATURES, never add model complexity.

So the baselines are built FIRST and scored on exactly the same rows. A model
that cannot beat "it is raining now, so it will keep raining" has earned
nothing, and saying so is the whole point of having a baseline.

HONEST THRESHOLDS
-----------------
Heads are 5 mm/h and 10 mm/h, not the charter's 15 mm/h — see the long note in
features/dynamic.py. 15 mm/h has 63 test positives in ERA5 and cannot support a
believable CSI. These are ERA5-scale thresholds and the reports say so.

    python models/raincast_v0.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "cube" / "raincast_table.parquet"
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"

# WINDOW framing: "heavy rain within the next W hours" (see features/dynamic.py).
WINDOWS = [1, 3, 6]
HEADS = {"p5": 5.0, "p10": 10.0}              # peak hourly rate inside the window
ACC_HEADS = {"acc10": 10.0, "acc20": 20.0}    # accumulated total over the window

# Columns that are targets, identifiers, or otherwise not legitimate features.
DROP_PREFIX = ("y_",)
DROP_EXACT = {
    "valid_time", "issue_time", "date", "split", "lat", "lon",
    "precip_obs",        # the answer at time t — never a feature for t+lead
    "imd_rain_daily",    # daily truth; would leak the day's total
    "month",
}


def contingency(y: np.ndarray, pred: np.ndarray) -> dict:
    """CSI / POD / FAR from a binary forecast. The standard meteorological scores."""
    hits = float(((pred == 1) & (y == 1)).sum())
    miss = float(((pred == 0) & (y == 1)).sum())
    fa = float(((pred == 1) & (y == 0)).sum())
    return {
        "hits": hits, "misses": miss, "false_alarms": fa,
        "POD": hits / (hits + miss) if (hits + miss) else 0.0,
        "FAR": fa / (hits + fa) if (hits + fa) else 0.0,
        "CSI": hits / (hits + miss + fa) if (hits + miss + fa) else 0.0,
    }


def best_threshold(y: np.ndarray, p: np.ndarray) -> tuple[float, dict]:
    """
    The operating point: the probability cut that MAXIMISES CSI on validation.
    Never a magic 0.5 (charter §7.4) — and the whole curve is reported.
    """
    best, best_t = None, 0.5
    for t in np.round(np.arange(0.02, 0.96, 0.02), 2):
        m = contingency(y, (p >= t).astype(int))
        if best is None or m["CSI"] > best["CSI"]:
            best, best_t = m, float(t)
    return best_t, best


MIN_TRAIN_COVERAGE = 0.80


def feature_columns(df: pd.DataFrame) -> list[str]:
    """
    Features, with TEMPORALLY-INCONSISTENT columns dropped.

    WHY THIS FILTER EXISTS — it came out of the ablation (eval/ablation.py),
    which found that removing NWP entirely IMPROVED CSI from 0.098 to 0.124.
    That looked absurd until the cause was measured: NWP coverage starts at
    different dates (GFS Mar 2021, ICON Nov 2022, ECMWF Feb 2024,
    previous_dayN Jan 2024), so a column's MISSINGNESS correlates with the
    year. In TEST 2025 every model is present — a pattern the model never saw
    in training — so those columns mislead instead of inform.

    Restricting to columns with >=80% coverage in the TRAINING split recovered
    most of the loss (0.098 -> 0.116). Coverage is computed on TRAIN ONLY, so
    this decision cannot see the test year.

    The deeper finding is worth stating out loud rather than patching over: at
    0-6 h lead, observation-based advection beats global NWP (raw GFS CSI
    0.015). That is precisely the nowcast gap this project exists to fill, and
    it is consistent with RainFuse, where NWP at 6-72 h IS the signal and we
    beat it on Brier.
    """
    cand = [
        c for c in df.columns
        if not c.startswith(DROP_PREFIX)
        and c not in DROP_EXACT
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    tr = df[df.split == "train"]
    keep, dropped = [], []
    for c in cand:
        cov = float(tr[c].notna().mean())
        (keep if cov >= MIN_TRAIN_COVERAGE else dropped).append((c, cov))
    if dropped:
        print(f"  dropped {len(dropped)} columns below "
              f"{MIN_TRAIN_COVERAGE:.0%} train coverage:")
        for c, cov in sorted(dropped, key=lambda kv: kv[1]):
            print(f"    {c:<32} {cov:.1%}")
    return [c for c, _ in keep]


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1])
        if m.sum() < 20:
            continue
        out.append({
            "bin_center": round(float((edges[i] + edges[i + 1]) / 2), 3),
            "predicted": round(float(p[m].mean()), 4),
            "observed": round(float(y[m].mean()), 4),
            "count": int(m.sum()),
        })
    return out


def main() -> int:
    if not TABLE.exists():
        print("run features/dynamic.py first")
        return 1
    df = pd.read_parquet(TABLE)
    print(f"RainCast-v0   table {len(df):,} rows")

    tr = df[df.split == "train"]
    va = df[df.split == "val"]
    te = df[df.split == "test"]
    print(f"  train {len(tr):,}   val {len(va):,}   test {len(te):,}")

    feats = feature_columns(df)
    print(f"  {len(feats)} features\n")

    results, reliab, skill = [], {}, []
    MODELS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)

    for head, thr in {**HEADS, **ACC_HEADS}.items():
        is_acc = head in ACC_HEADS
        for lead in WINDOWS:
            ycol = f"y_{head}_w{lead}"
            ytr, yva, yte = tr[ycol].to_numpy(), va[ycol].to_numpy(), te[ycol].to_numpy()
            if yte.sum() < 20:
                print(f"  SKIP {ycol}: only {int(yte.sum())} test positives")
                continue

            # ---------------------------------------------------- BASELINES
            # Persistence must be framed the SAME way as the target, or the
            # comparison is rigged. For a window-MAX head, persistence is "it is
            # raining >= thr right now". For an ACCUMULATION head it is "the last
            # W hours already accumulated >= thr" — the honest like-for-like.
            if is_acc:
                past = te.get(f"precip_acc{lead}", te["precip_obs"])
                base_pers = (past.to_numpy() > thr).astype(int)
            else:
                base_pers = (te["precip_obs"].to_numpy() > thr).astype(int)
            m_pers = contingency(yte, base_pers)

            # (b) raw NWP at the same valid time, thresholded identically.
            #     NaN where that model had not started publishing yet -> counts
            #     as "no rain forecast", which is what a user would actually see.
            nwp = te["precipitation_gfs_seamless"].to_numpy() if \
                "precipitation_gfs_seamless" in te else np.full(len(te), np.nan)
            # For accumulation heads compare against the NWP total over the same
            # window, not a single hour — again, like-for-like.
            nwp_cmp = np.nan_to_num(nwp, nan=0.0) * (lead if is_acc else 1)
            m_nwp = contingency(yte, (nwp_cmp > thr).astype(int))

            # ------------------------------------------------------- MODEL
            params = dict(objective="binary", learning_rate=0.05, num_leaves=63,
                          feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                          min_data_in_leaf=50, verbose=-1)
            # NOTE: no scale_pos_weight. The first run used it and the model
            # over-predicted massively (FAR > 0.98). Isotonic calibration plus a
            # CSI-optimised operating point handle the class imbalance properly;
            # reweighting on top of them just distorts the probabilities that the
            # calibration is then asked to repair.
            ds_tr = lgb.Dataset(tr[feats], ytr)
            ds_va = lgb.Dataset(va[feats], yva, reference=ds_tr)
            booster = lgb.train(params, ds_tr, num_boost_round=500,
                                valid_sets=[ds_va],
                                callbacks=[lgb.early_stopping(40, verbose=False)])

            p_va = booster.predict(va[feats], num_iteration=booster.best_iteration)
            p_te = booster.predict(te[feats], num_iteration=booster.best_iteration)

            # ------------------------------------ isotonic calibration on VAL only
            iso = IsotonicRegression(out_of_bounds="clip").fit(p_va, yva)
            p_te_cal = iso.predict(p_te)

            # operating point chosen on VAL, applied to TEST
            op, _ = best_threshold(yva, iso.predict(p_va))
            m_model = contingency(yte, (p_te_cal >= op).astype(int))

            row = {
                "head": head, "threshold_mm": thr, "window_h": lead,
                "test_positives": int(yte.sum()),
                "operating_point": op,
                "model": {**m_model,
                          "brier": round(float(brier_score_loss(yte, p_te_cal)), 5),
                          "auc_pr": round(float(average_precision_score(yte, p_te_cal)), 4)},
                "persistence": m_pers,
                "raw_nwp_gfs": m_nwp,
                "beats_persistence": m_model["CSI"] > m_pers["CSI"],
                "beats_raw_nwp": m_model["CSI"] > m_nwp["CSI"],
                "best_iteration": booster.best_iteration,
            }
            results.append(row)
            reliab[f"raincast_{head}_w{lead}"] = reliability(yte, p_te_cal)
            skill.append({"lead_h": lead, "csi": round(m_model["CSI"], 4),
                          "model": f"RainCast {head}"})
            skill.append({"lead_h": lead, "csi": round(m_pers["CSI"], 4),
                          "model": f"persistence {head}"})
            skill.append({"lead_h": lead, "csi": round(m_nwp["CSI"], 4),
                          "model": f"raw GFS {head}"})

            flag = "PASS" if (row["beats_persistence"] and row["beats_raw_nwp"]) else "FAIL"
            print(f"  [{flag}] {head:<6} w{lead}h  "
                  f"CSI model {m_model['CSI']:.3f} | pers {m_pers['CSI']:.3f} | "
                  f"gfs {m_nwp['CSI']:.3f}   POD {m_model['POD']:.3f} "
                  f"FAR {m_model['FAR']:.3f}  op={op}")

            booster.save_model(str(MODELS / f"raincast_v0_{head}_w{lead}.txt"))

    # ------------------------------------------------------------- summary
    passed = sum(1 for r in results if r["beats_persistence"] and r["beats_raw_nwp"])
    print(f"\n  GATE: {passed}/{len(results)} head-lead combinations beat BOTH baselines")

    (REPORTS / "raincast_metrics.json").write_text(json.dumps(
        {"results": results, "reliability": reliab, "skill_vs_lead": skill,
         "note": ("ERA5-scale thresholds. ERA5 smooths convective extremes, so "
                  "5 mm/h here corresponds to substantially higher point rainfall. "
                  "Charter's 15 mm/h head had only 63 test positives and was dropped.")},
        indent=2))
    print(f"  -> reports/raincast_metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
