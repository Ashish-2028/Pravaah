#!/usr/bin/env python
"""
PRAVAAH — dry-day negatives for InundaNet (fixes a fundamental label flaw).

THE PROBLEM THIS SOLVES
-----------------------
The original label set drew ALL negatives from the SAME event windows as the
positives — spatially far (>1 km) but temporally identical. Consequence: within
any labelled pair, rainfall is nearly the same for the positive and the
negative, so rain carries no power to separate them. The model correctly
concluded that rain is uninformative and became a pure static-susceptibility
model. Measured response of InundaNet-v0 on a fixed median urban cell:

        rain_sum   0 mm -> p_flood 0.0041
        rain_sum  50 mm -> p_flood 0.0050
        rain_sum 200 mm -> p_flood 0.0052

That is flat, and non-monotonic in places. A model that does not respond to
rainfall cannot claim to turn rain into water, which is the entire premise of
InundaNet and the project's USP.

THE FIX
-------
Add TEMPORAL negatives: the SAME cells that flood during an event, sampled on
DRY days. Now the contrast the model sees is

    same place + heavy rain  -> flooded
    same place + no rain     -> not flooded

which is exactly the causal relationship we want it to learn, and it cannot be
explained away by terrain because the terrain is identical in both rows.

This also fixes the urban/rural sampling artifact for free: a dry-day negative
sits on a cell with identical imperviousness to its own positive.

    python features/dry_negatives.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LABELS = ROOT / "data" / "labels" / "inunda_labels.parquet"
CUBE = ROOT / "cube" / "ncr_cube.parquet"
OUT = ROOT / "data" / "labels" / "inunda_labels_v2.parquet"

DRY_PER_POSITIVE = 3          # dry days sampled per positive cell
DRY_MAX_DAILY_MM = 2.0        # a "dry" day: essentially no rain at that point
MONSOON = [6, 7, 8, 9]
RNG = np.random.default_rng(20240628)


def main() -> int:
    lab = pd.read_parquet(LABELS)
    pos = lab[lab.label == 1].copy()
    print(f"  {len(lab):,} original rows, {len(pos):,} positive")

    cube = pd.read_parquet(CUBE, columns=["lat", "lon", "valid_time", "precip_obs"])
    cube["date"] = cube["valid_time"].dt.tz_convert("UTC").dt.normalize()
    daily = (cube.groupby(["lat", "lon", "date"], as_index=False)
                 .agg(rain_sum=("precip_obs", "sum"),
                      rain_max=("precip_obs", "max")))
    daily = daily[daily["date"].dt.month.isin(MONSOON)]

    # Candidate dry days per lattice point.
    dry = daily[daily.rain_sum <= DRY_MAX_DAILY_MM]
    print(f"  {len(dry):,} dry point-days available "
          f"(<= {DRY_MAX_DAILY_MM} mm, monsoon only)")

    # Map each positive cell to its lattice point (same rule as elsewhere).
    pts = daily[["lat", "lon"]].drop_duplicates().to_numpy()
    cells = pos[["lat", "lon"]].drop_duplicates()
    xw = []
    for la, lo in cells.to_numpy():
        d = (pts[:, 0] - la) ** 2 + (pts[:, 1] - lo) ** 2
        p = pts[int(d.argmin())]
        xw.append({"lat": la, "lon": lo, "plat": float(p[0]), "plon": float(p[1])})
    pos = pos.merge(pd.DataFrame(xw), on=["lat", "lon"], how="left")

    dry_by_pt = {k: g["date"].to_numpy() for k, g in dry.groupby(["lat", "lon"])}

    rows = []
    for _, r in pos.iterrows():
        cand = dry_by_pt.get((r.plat, r.plon))
        if cand is None or len(cand) == 0:
            continue
        for d in RNG.choice(cand, min(DRY_PER_POSITIVE, len(cand)), replace=False):
            n = r.to_dict()
            n["label"] = 0
            n["event_id"] = f"dry-{pd.Timestamp(d).date()}"
            # Match the existing column dtype exactly. The original table
            # stores these as strings; writing Timestamps here makes the
            # parquet write fail with an ArrowTypeError on a mixed column.
            ds = str(pd.Timestamp(d).date())
            n["event_start"] = ds
            n["event_end"] = ds
            n["event_origin"] = "dry_day_negative"
            n["source"] = "temporal_negative"
            # These columns describe the LABEL PROCESS and are blacklisted as
            # features anyway; blank them so nothing can key off them.
            for c in ("point_id", "point_name", "point_rain_mm", "rain_confirmed"):
                n[c] = None
            n["sample_weight"] = 1.0
            rows.append(n)

    dryneg = pd.DataFrame(rows).drop(columns=["plat", "plon"], errors="ignore")
    out = pd.concat([lab, dryneg], ignore_index=True)

    print(f"  + {len(dryneg):,} dry-day negatives on the SAME cells")
    print(f"  -> {len(out):,} rows, {int(out.label.sum()):,} positive "
          f"({out.label.mean():.4f} base rate)")
    out.to_parquet(OUT, index=False)
    print(f"  wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
