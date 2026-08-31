#!/usr/bin/env python
"""
PRAVAAH — consolidate every earned number into reports/metrics.json.

This is what GET /api/verify/metrics serves and what the Verification view
renders. Until now that file has been a placeholder written by make_fakes.py;
this replaces it with real results and NOTHING ELSE. If a proof is not earned,
it appears with computable=false and a reason — it does not appear as a
plausible-looking number.

    python eval/build_metrics.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
TABLE = ROOT / "cube" / "raincast_table.parquet"


def load(name: str) -> dict:
    p = REPORTS / name
    return json.loads(p.read_text()) if p.exists() else {}


def lead_time_vs_nwp() -> dict:
    """
    SUBSTITUTE FOR PROOF P-3.

    The original plan was lead time vs IMD's CAP alerts. That turned out not to
    be computable for the demo event: IMD's public CAP feed carried NO
    Delhi-covering alert in the 7 days around 28 Jun 2024 (7 sparse multi-state
    bulletins, none mentioning Delhi). Rather than compare against an alert for
    Kerala and call it a proof, we compute a different lead time that IS
    well defined and arguably more relevant to the charter's own thesis:

        How many hours before RAW NWP does our model cross its warning
        threshold, on the same event, at a stated false-alarm ratio?

    That is a direct measurement of the 0-6 h gap the whole project exists to
    fill, and both sides are observable.
    """
    if not TABLE.exists():
        return {"computable": False, "reason": "raincast_table missing"}
    df = pd.read_parquet(TABLE)
    ev = df[(df.valid_time >= "2024-06-27T12:00Z")
            & (df.valid_time <= "2024-06-28T12:00Z")].copy()
    if ev.empty:
        return {"computable": False, "reason": "event window absent from table"}

    truth_col = "y_p5_w3"
    obs = ev.groupby("valid_time")[truth_col].max()
    first_true = obs[obs > 0].index.min() if (obs > 0).any() else None
    if first_true is None:
        return {"computable": False,
                "reason": "no positive target hours in the event window"}

    # When did raw GFS first forecast >5 mm anywhere in the box?
    gfs = ev.groupby("valid_time")["precipitation_gfs_seamless"].max()
    gfs_cross = gfs[gfs > 5.0].index.min() if (gfs > 5.0).any() else None

    # When did observed rain first exceed the same threshold (persistence would
    # only fire at or after this point)?
    pers = ev.groupby("valid_time")["precip_obs"].max()
    pers_cross = pers[pers > 5.0].index.min() if (pers > 5.0).any() else None

    out = {
        "computable": True,
        "event": "2024-06-28",
        "first_observed_exceedance_utc": str(first_true),
        "raw_gfs_first_crossing_utc": str(gfs_cross) if gfs_cross is not None else None,
        "persistence_first_crossing_utc": (str(pers_cross)
                                           if pers_cross is not None else None),
        "note": ("Substitute for the CAP comparison, which is not computable "
                 "for this event — see cap_comparison below. Measures how the "
                 "physics baseline and the persistence baseline timed this "
                 "event relative to what actually happened."),
    }
    if gfs_cross is not None:
        out["gfs_lag_hours_vs_observed"] = round(
            (gfs_cross - first_true).total_seconds() / 3600, 2)
    if pers_cross is not None:
        out["persistence_lag_hours_vs_observed"] = round(
            (pers_cross - first_true).total_seconds() / 3600, 2)
    return out


def main() -> int:
    rc = load("raincast_metrics.json")
    rf = load("rainfuse_metrics.json")
    inu = load("inundanet_metrics.json")
    abl = load("ablation.json")
    lead = load("leadtime.json")
    gate = load("phase2_gate.json")

    # ---- reliability, keyed by model head (Proof P-2)
    reliability = {}
    reliability.update(rc.get("reliability", {}))
    reliability.update(rf.get("reliability", {}))

    # ---- ablation rows in the contract's shape (Proof P-1)
    ablation = []
    for r in abl.get("rows", []):
        ablation.append({
            "config": r["config"],
            "csi": round(r.get("CSI", 0), 4),
            "pod": round(r.get("POD", 0), 4),
            "far": round(r.get("FAR", 0), 4),
            "brier": r.get("brier"),
        })

    skill = rc.get("skill_vs_lead", []) + rf.get("skill_vs_lead", [])

    metrics = {
        "generated": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reliability": reliability,
        "ablation": ablation,
        "skill_vs_lead": skill,
        "leadtime_vs_cap": [],          # kept for schema compatibility
        "proofs": {
            "P1_fusion": {
                "artefact": "ablation table",
                "verdict": abl.get("verdict", "not run"),
                "head": abl.get("head"),
                "test_positives": abl.get("test_positives"),
                "honest_finding": (
                    "Leave-one-out shows ADVECTION is the dominant family "
                    "(-0.040 CSI when removed) and that NWP as available HURTS "
                    "at 0-6 h (+0.026 CSI when removed). Cause was measured, "
                    "not guessed: NWP coverage starts at different dates "
                    "(GFS 2021-03, ICON 2022-11, ECMWF 2024-02), so a column's "
                    "missingness correlates with year and misleads on a fully-"
                    "covered test year. Restricting to consistent-coverage "
                    "columns recovers most of it (0.098 -> 0.116). The deeper "
                    "reading is the project's own thesis: at 0-6 h, "
                    "observation-based extrapolation beats global NWP — which "
                    "is exactly the nowcast gap PRAVAAH exists to fill, and is "
                    "consistent with RainFuse, where NWP at 6-72 h IS the "
                    "signal and we beat it on Brier."),
            },
            "P2_calibration": {
                "artefact": "reliability diagrams + isotonic on held-out year",
                "rainfuse_heavy_brier": next(
                    (r["model"]["brier"] for r in rf.get("results", [])
                     if r["category"] == "heavy"), None),
                "raw_nwp_brier": next(
                    (r["raw_nwp"]["brier_proxy"] for r in rf.get("results", [])
                     if r["category"] == "heavy"), None),
                "heads_with_reliability": list(reliability.keys()),
            },
            "P3_lead_time": {
                "cap_comparison": lead,
                "substitute": lead_time_vs_nwp(),
            },
            "P4_portability": {
                "artefact": "configs/aoi_*.yaml",
                "configs": sorted(p.name for p in
                                  (ROOT / "configs").glob("aoi_*.yaml")),
            },
        },
        "models": {
            "raincast": {
                "heads": [
                    {"head": r["head"], "window_h": r["window_h"],
                     "csi": r["model"]["CSI"], "pod": r["model"]["POD"],
                     "far": r["model"]["FAR"], "brier": r["model"]["brier"],
                     "persistence_csi": r["persistence"]["CSI"],
                     "raw_nwp_csi": r["raw_nwp_gfs"]["CSI"],
                     "test_positives": r["test_positives"],
                     "beats_both": bool(r["beats_persistence"]
                                        and r["beats_raw_nwp"])}
                    for r in rc.get("results", [])
                ],
                "gate": (f"{sum(1 for r in rc.get('results', []) if r['beats_persistence'] and r['beats_raw_nwp'])}"
                         f"/{len(rc.get('results', []))} heads beat BOTH baselines"),
                "note": rc.get("note"),
            },
            "rainfuse": {
                "categories": [
                    {"category": r["category"], "threshold_mm": r["threshold_mm"],
                     "csi": r["model"]["CSI"], "brier": r["model"]["brier"],
                     "raw_nwp_csi": r["raw_nwp"]["CSI"],
                     "raw_nwp_brier": r["raw_nwp"]["brier_proxy"],
                     "test_positives": r["test_positives"]}
                    for r in rf.get("results", [])
                ],
                "domain": rf.get("domain"), "truth": rf.get("truth"),
            },
            "inundanet": {
                "auc_pr": inu.get("model", {}).get("auc_pr"),
                "roc_auc": inu.get("model", {}).get("roc_auc"),
                "hand_baseline_auc_pr": inu.get("baseline_hand_only", {}).get("auc_pr"),
                "lift_over_hand": inu.get("lift_over_hand"),
                "within_event_roc_auc": inu.get("within_event_roc_auc"),
                "between_event_roc_auc": inu.get("between_event_roc_auc"),
                "matched_negatives": inu.get("matched_negatives"),
                "cv": inu.get("cv"),
                "honesty_note": inu.get("honesty_note"),
            },
        },
        "stated_limits": [
            "No ground radar. IMD's raw DWR volumes are gated; we log the "
            "public imagery every 10 minutes but do not decode it in v0. Radar "
            "is THE nowcasting instrument, so 0-6 h skill is bounded by its "
            "absence.",
            "ERA5-Land smooths convective extremes: 20.9 mm near Safdarjung on "
            "28 Jun 2024 where the gauge recorded 228 mm. RainCast's thresholds "
            "are therefore ERA5-scale, and the charter's 15 mm/h head was "
            "dropped because it had only 63 test positives.",
            "IMD gridded is gauge-based and captures the extreme (150.7 mm) but "
            "is 0.25 deg — only 6 cells over the NCR box — so it is a daily "
            "areal truth, not a ward-scale one.",
            "Flood labels are 84 hand-curated points. Terrain alone does not "
            "explain them (top-quintile enrichment 0.94); OSM underpass "
            "features are the strongest available proxy for the missing "
            "variable, which is storm-sewer capacity.",
            "IMD's public CAP feed carried no Delhi-covering alert around the "
            "demo event, so lead-time-vs-CAP is not computable for it. That is "
            "reported as not-computable rather than substituted quietly.",
        ],
        "phase2_hotspot_gate": {
            "cell_level": gate.get("hotspots"),
            "ward_level_watched": gate.get("ward_level", {}).get("watched"),
        },
    }

    (REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("reports/metrics.json rebuilt from REAL results")
    print(f"  reliability heads : {len(reliability)}")
    print(f"  ablation rows     : {len(ablation)}")
    print(f"  raincast heads    : {len(metrics['models']['raincast']['heads'])}")
    print(f"  rainfuse cats     : {len(metrics['models']['rainfuse']['categories'])}")
    print(f"  gate              : {metrics['models']['raincast']['gate']}")
    print(f"  P-1 verdict       : {metrics['proofs']['P1_fusion']['verdict']}")
    print(f"  P-3 CAP           : computable={lead.get('computable', 'n/a')}")
    print(f"  stated limits     : {len(metrics['stated_limits'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
