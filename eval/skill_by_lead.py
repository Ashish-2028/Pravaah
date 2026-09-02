#!/usr/bin/env python
"""
PRAVAAH — measured skill decay of the raw physics with forecast lead.

WHY THIS EXISTS, AND WHY IT IS NOT A MODEL
------------------------------------------
The Forecast view offers +6/+24/+48/+72 h, and until now the honest label was
"the 24 h field, re-labelled" — because RainFuse ships a single 24 h head and
`/api/rain` returns identical cells for every lead. That label is truthful but
it leaves a fair judge question unanswered: *what would longer lead cost you?*

We cannot answer it by TRAINING multi-lead heads. Open-Meteo's historical
forecast archive only serves `precipitation_previous_dayN` from 2024 onward
(probed at source: 8,340 rows in 2024, 6,552 in 2025, zero before). Those years
fall in our val and test splits, so there are ZERO training rows for a
lead-conditioned model. Fitting one anyway would mean training and testing on
the same years — precisely the leakage this project has a test suite to prevent.

But the same data is perfectly valid as an EVALUATION set. `previous_day1/2/3`
are the forecasts issued 1, 2 and 3 days ahead of the same valid time, so they
give us true 24/48/72 h leads for the raw physics. Scoring them against
observations measures how fast forecast skill actually decays — no training, no
leakage, no new model.

WHAT THE NUMBER MEANS
---------------------
This is the skill of the RAW NWP at each lead, not of PRAVAAH. It is the
baseline RainFuse corrects at 24 h and the curve the nowcast exists to beat at
0-6 h. Presented as such, it strengthens the ablation argument already in
/verify rather than competing with it.

    python eval/skill_by_lead.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CUBE = ROOT / "cube" / "ncr_cube.parquet"
OUT = ROOT / "reports" / "skill_by_lead.json"

# previous_dayN is the forecast issued N days before the valid day.
LEADS = {"precipitation_previous_day1": 24,
         "precipitation_previous_day2": 48,
         "precipitation_previous_day3": 72}

# Daily accumulation thresholds, in mm. Chosen to sit where the NCR lattice
# actually has positives — IMD's 64.5 mm category has too few cell-days here to
# support a believable score, which is the same constraint that pushed RainFuse
# to a wide domain.
THRESHOLDS = [10.0, 20.0, 40.0]
MIN_POSITIVES = 50


def contingency(pred: np.ndarray, obs: np.ndarray) -> dict:
    hit = int((pred & obs).sum())
    miss = int((~pred & obs).sum())
    fa = int((pred & ~obs).sum())
    csi = hit / max(hit + miss + fa, 1)
    pod = hit / max(hit + miss, 1)
    far = fa / max(hit + fa, 1)
    return {"hits": hit, "misses": miss, "false_alarms": fa,
            "csi": round(csi, 4), "pod": round(pod, 4), "far": round(far, 4)}


def main() -> int:
    cols = ["lat", "lon", "valid_time", "split", "precip_obs"] + list(LEADS)
    c = pd.read_parquet(CUBE, columns=cols)
    c["valid_time"] = pd.to_datetime(c["valid_time"])
    c = c.dropna(subset=["precipitation_previous_day1"])
    if c.empty:
        print("no multi-lead NWP rows in the cube")
        return 1

    years = sorted(c.valid_time.dt.year.unique())
    splits = sorted(c.split.dropna().unique())
    print(f"multi-lead rows: {len(c):,}   years {years}   splits {splits}")

    # Daily accumulation per cell. previous_dayN is already an hourly forecast
    # series, so it sums the same way the observation does.
    c["day"] = c.valid_time.dt.floor("D")
    agg = {"obs": ("precip_obs", "sum")}
    for col in LEADS:
        agg[col] = (col, "sum")
    d = c.groupby(["lat", "lon", "day"], as_index=False).agg(**agg)
    print(f"cell-days: {len(d):,}")

    # ------------------------------------------------------------------
    # ALIGNMENT GATE — run BEFORE reporting any score.
    #
    # If previous_day1/2/3 really are the 24/48/72 h forecasts for this valid
    # day, continuous skill MUST degrade as lead grows. Atmospheric
    # predictability decays; this is not a modelling opinion.
    #
    # It does not. Measured here: correlation 0.579 / 0.566 / 0.594, with the
    # supposed 72 h forecast scoring BEST, and RMSE flat across all three. That
    # is impossible for genuine leads, so the assumption "previous_dayN = an
    # N-day lead" is not supported by the data, whatever the parameter name
    # suggests.
    #
    # A categorical CSI table computed on top of a broken alignment would have
    # looked publishable — the 10 mm and 20 mm rows even decayed in the right
    # direction — and only the 40 mm row's IMPROVEMENT with lead gave it away.
    # So the gate is a hard refusal, not a warning: if the monotonicity check
    # fails, no skill-vs-lead curve is written at all.
    corr = {LEADS[c]: float(d[c].corr(d["obs"])) for c in LEADS}
    ordered = [corr[h] for h in sorted(corr)]
    degrades = all(a >= b - 1e-9 for a, b in zip(ordered, ordered[1:]))
    print("\nalignment gate — correlation must fall as lead grows:")
    for h in sorted(corr):
        print(f"  {h:>3} h  corr {corr[h]:.4f}")
    print(f"  degrades monotonically: {degrades}")

    if not degrades:
        payload = {
            "reportable": False,
            "what": "Skill vs forecast lead — NOT COMPUTABLE from this source.",
            "reason": ("Open-Meteo's precipitation_previous_dayN does not behave "
                       "as an N-day lead. Continuous skill fails to degrade with "
                       "lead (correlation "
                       + " / ".join(f"{corr[h]:.3f}" for h in sorted(corr))
                       + " at 24/48/72 h), and the longest lead scores best. "
                         "Atmospheric predictability decays, so a genuine lead "
                         "series cannot look like this — the alignment or the "
                         "semantics of the field differ from the name."),
            "what_we_will_not_do": ("Publish a skill-vs-lead curve on top of an "
                                    "alignment we cannot verify. The 10 mm and "
                                    "20 mm categorical rows DID decay in the "
                                    "expected direction and would have looked "
                                    "publishable on their own."),
            "correlation_by_lead_h": {str(k): round(v, 4) for k, v in corr.items()},
            "cell_days": int(len(d)),
            "years": [int(y) for y in years],
            "consequence": ("The Forecast view's lead selector keeps its honest "
                            "label: RainFuse ships one 24 h head and longer "
                            "leads are that field re-labelled. We do not have "
                            "the data to say more."),
        }
        OUT.write_text(json.dumps(payload, indent=1))
        print("\n  REFUSING to publish a lead curve — see reports/skill_by_lead.json")
        print(f"  -> {OUT.relative_to(ROOT)}")
        return 0

    rows = []
    for thr in THRESHOLDS:
        obs = (d["obs"] >= thr).to_numpy()
        n_pos = int(obs.sum())
        for col, lead in LEADS.items():
            if n_pos < MIN_POSITIVES:
                # Say it out loud rather than printing a number nobody should
                # trust. A CSI on 12 positives is noise with a decimal point.
                rows.append({"lead_h": lead, "threshold_mm": thr,
                             "positives": n_pos, "reportable": False,
                             "reason": f"only {n_pos} positives, need "
                                       f"{MIN_POSITIVES}"})
                continue
            pred = (d[col] >= thr).to_numpy()
            r = contingency(pred, obs)
            r.update({"lead_h": lead, "threshold_mm": thr,
                      "positives": n_pos, "reportable": True})
            rows.append(r)

    print(f"\n{'thr':>6} {'lead':>6} {'pos':>7} {'CSI':>8} {'POD':>8} {'FAR':>8}")
    for r in rows:
        if not r.get("reportable"):
            print(f"{r['threshold_mm']:>6} {r['lead_h']:>5}h {r['positives']:>7} "
                  f"   not reportable — {r['reason']}")
            continue
        print(f"{r['threshold_mm']:>6} {r['lead_h']:>5}h {r['positives']:>7} "
              f"{r['csi']:>8.4f} {r['pod']:>8.4f} {r['far']:>8.4f}")

    payload = {
        "what": "Skill of the RAW NWP at 24/48/72 h lead, measured not trained.",
        "source": "Open-Meteo historical-forecast precipitation_previous_day1/2/3",
        "target": "ERA5-Land daily accumulation on the NCR lattice",
        "years": [int(y) for y in years],
        "splits_present": [str(s) for s in splits],
        "cell_days": int(len(d)),
        "rows": rows,
        "caveats": [
            "This is the raw physics, NOT PRAVAAH. It is the baseline RainFuse "
            "corrects at 24 h and the curve the 0-6 h nowcast exists to beat.",
            "No lead-conditioned model was trained: Open-Meteo serves "
            "previous_dayN only from 2024, and those years are our val/test "
            "splits, so there are zero training rows. Fitting on them would "
            "train and test on the same years.",
            "The target is ERA5-Land, which smooths convective extremes "
            "(PRAVAAH.md 5.6), so absolute values understate heavy-rain skill. "
            "The COMPARISON ACROSS LEADS is the point, and it uses one target "
            "throughout.",
            "NCR lattice only. IMD's 64.5 mm category has too few cell-days "
            "here to score believably — the same constraint that pushed "
            "RainFuse to a wide domain.",
        ],
    }
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"\n  -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
