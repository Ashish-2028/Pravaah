#!/usr/bin/env python
"""
PRAVAAH — PROOF P-1: does fusion actually help? (BUILD_PLAN P13-T1)

THE CLAIM WE HAVE TO EARN
-------------------------
"PRAVAAH fuses four families of weather information into one cube." Judges are
entitled to ask: does that fusion do anything, or is it four sources decorating
a model that one source could have produced?

This answers it by RETRAINING the identical model with one source family
REMOVED at a time and re-scoring on the same held-out year. If the all-sources
row does not top the table, we say so — a negative ablation is a real result
and hiding it would be the fastest way to lose credibility.

FAMILIES
--------
  obs        ERA5 lags, accumulations, antecedent indices  (what has happened)
  advection  neighbour rain, drift gradients, box stats    (where it is going)
  nwp        ECMWF/GFS/ICON + CAPE/CIN/lifted index        (what physics says)
  static     HAND, TWI, slope, impervious, dist-to-drain   (what the ground is)
  time       hour/day-of-year cyclical encodings           (when it is)

Every row is trained and scored on IDENTICAL rows, so differences are the
feature set and nothing else.

    python eval/ablation.py
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
sys.path.insert(0, str(ROOT))
from models.raincast_v0 import contingency, best_threshold  # noqa: E402

TABLE = ROOT / "cube" / "raincast_table.parquet"
REPORTS = ROOT / "reports"

# The head to run the ablation on: the primary one, with the most test
# positives, so the comparison is stable rather than noise.
HEAD = "y_p5_w3"
THRESH = 5.0

DROP_EXACT = {"valid_time", "issue_time", "date", "split", "lat", "lon",
              "precip_obs", "imd_rain_daily", "month"}


def classify(col: str) -> str:
    if col.startswith(("nb_", "box_")):
        return "advection"
    if col.startswith("static_"):
        return "static"
    if col.startswith(("precipitation_", "nwp_", "d_ecmwf", "d_gfs",
                       "cape", "convective_inhibition", "lifted_index")):
        return "nwp"
    if col in {"hour_sin", "hour_cos", "doy_sin", "doy_cos"}:
        return "time"
    return "obs"


def run(tr, va, te, feats, ycol) -> dict:
    ytr, yva, yte = (tr[ycol].to_numpy(), va[ycol].to_numpy(), te[ycol].to_numpy())
    params = dict(objective="binary", learning_rate=0.05, num_leaves=63,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                  min_data_in_leaf=50, verbose=-1)
    ds = lgb.Dataset(tr[feats], ytr)
    dv = lgb.Dataset(va[feats], yva, reference=ds)
    b = lgb.train(params, ds, 500, valid_sets=[dv],
                  callbacks=[lgb.early_stopping(40, verbose=False)])
    pv = b.predict(va[feats], num_iteration=b.best_iteration)
    pt = b.predict(te[feats], num_iteration=b.best_iteration)
    iso = IsotonicRegression(out_of_bounds="clip").fit(pv, yva)
    ptc = iso.predict(pt)
    # raincast_v0.best_threshold returns (threshold, metrics); take the first.
    op, _ = best_threshold(yva, iso.predict(pv))
    m = contingency(yte, (ptc >= op).astype(int))
    return {**m,
            "brier": round(float(brier_score_loss(yte, ptc)), 5),
            "auc_pr": round(float(average_precision_score(yte, ptc)), 4),
            "operating_point": op,
            "n_features": len(feats)}


def main() -> int:
    df = pd.read_parquet(TABLE)
    tr, va, te = (df[df.split == "train"], df[df.split == "val"],
                  df[df.split == "test"])
    allf = [c for c in df.columns
            if not c.startswith("y_") and c not in DROP_EXACT
            and pd.api.types.is_numeric_dtype(df[c])]
    fam: dict[str, list[str]] = {}
    for c in allf:
        fam.setdefault(classify(c), []).append(c)

    print("PROOF P-1 — fusion ablation")
    print(f"  head {HEAD} (>{THRESH} mm within 3 h), test positives "
          f"{int(te[HEAD].sum()):,}")
    for k, v in sorted(fam.items()):
        print(f"    {k:<10} {len(v):>3} features")
    print()

    rows = []
    base = run(tr, va, te, allf, HEAD)
    rows.append({"config": "ALL SOURCES (fusion)", **base})
    print(f"  {'ALL SOURCES (fusion)':<26} CSI {base['CSI']:.4f}  "
          f"POD {base['POD']:.3f}  FAR {base['FAR']:.3f}  Brier {base['brier']:.5f}")

    # leave-one-family-out
    for name in sorted(fam):
        sub = [c for c in allf if classify(c) != name]
        if not sub:
            continue
        r = run(tr, va, te, sub, HEAD)
        delta = base["CSI"] - r["CSI"]
        rows.append({"config": f"without {name}", **r,
                     "csi_drop_vs_fusion": round(delta, 4)})
        print(f"  {'without ' + name:<26} CSI {r['CSI']:.4f}  "
              f"POD {r['POD']:.3f}  FAR {r['FAR']:.3f}  Brier {r['brier']:.5f}   "
              f"{'-' if delta > 0 else '+'}{abs(delta):.4f} vs fusion")

    # single-family models: can any ONE source do the job alone?
    for name in sorted(fam):
        r = run(tr, va, te, fam[name], HEAD)
        rows.append({"config": f"{name} only", **r})
        print(f"  {name + ' only':<26} CSI {r['CSI']:.4f}  "
              f"POD {r['POD']:.3f}  FAR {r['FAR']:.3f}")

    # ---- DIAGNOSIS ROW. The leave-one-out above shows NWP HURTS. Hypothesis:
    # NWP coverage is temporally inconsistent (GFS from Mar 2021, ICON from
    # Nov 2022, ECMWF only from Feb 2024, previous_dayN from Jan 2024), so the
    # MISSINGNESS PATTERN correlates with year. In TEST 2025 coverage is 100%,
    # a distribution the model never saw in training — so those columns mislead
    # rather than inform. Test it by keeping only the NWP columns whose coverage
    # is consistent across train AND test (GFS-derived, plus the instability
    # fields which share GFS's 2021 start).
    consistent = [c for c in allf
                  if classify(c) != "nwp"
                  or ("gfs" in c or c in {"cape", "convective_inhibition",
                                          "lifted_index"})]
    r = run(tr, va, te, consistent, HEAD)
    rows.append({"config": "fusion, NWP limited to consistent-coverage cols",
                 **r, "csi_drop_vs_fusion": round(base["CSI"] - r["CSI"], 4)})
    print(f"  {'fusion (consistent NWP)':<26} CSI {r['CSI']:.4f}  "
          f"POD {r['POD']:.3f}  FAR {r['FAR']:.3f}  Brier {r['brier']:.5f}")

    # non-learned baselines on the same rows
    pers = (te["precip_obs"].to_numpy() > THRESH).astype(int)
    mp = contingency(te[HEAD].to_numpy(), pers)
    rows.append({"config": "persistence (no ML)", **mp})
    gfs = np.nan_to_num(te.get("precipitation_gfs_seamless",
                               pd.Series(np.zeros(len(te)))).to_numpy())
    mg = contingency(te[HEAD].to_numpy(), (gfs > THRESH).astype(int))
    rows.append({"config": "raw GFS (no ML)", **mg})
    print(f"  {'persistence (no ML)':<26} CSI {mp['CSI']:.4f}")
    print(f"  {'raw GFS (no ML)':<26} CSI {mg['CSI']:.4f}")

    best = max(rows, key=lambda r: r["CSI"])
    verdict = ("fusion wins" if best["config"] == "ALL SOURCES (fusion)"
               else f"NOT fusion — '{best['config']}' scores highest")
    print(f"\n  VERDICT: {verdict}")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "ablation.json").write_text(json.dumps(
        {"head": HEAD, "threshold_mm": THRESH,
         "test_positives": int(te[HEAD].sum()),
         "families": {k: len(v) for k, v in fam.items()},
         "rows": rows, "verdict": verdict}, indent=2))
    print("  -> reports/ablation.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
