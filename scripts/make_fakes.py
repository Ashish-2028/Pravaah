#!/usr/bin/env python
"""
PRAVAAH — generate contract-shaped FAKE outputs (BUILD_PLAN P1-T5).

Why this exists
---------------
The backend, the React app and the Streamlit harness are all built against
these files BEFORE any model exists. In Phase 8, scripts/precompute.py writes
real files with the identical shape and nothing downstream changes.

What is fake and what is real
-----------------------------
  REAL : ward geometry (DataMeet, 290 Delhi wards), ward names, the AOI,
         the timestamps, the file structure, the field names.
  FAKE : every number.

The storm is a deterministic synthetic event that grows 04:00 -> 07:30 and
decays after, so the Replay view has something believable to animate.

    conda run -n pravaah python scripts/make_fakes.py
"""
from __future__ import annotations

import json
import math
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
WARDS_RAW = ROOT / "data" / "raw" / "Delhi_Wards.geojson"
OUTPUTS = ROOT / "data" / "outputs"
REPORTS = ROOT / "reports"

SEED = 20240628
random.seed(SEED)


# --------------------------------------------------------------- helpers
def load_config() -> dict:
    with CONFIG.open() as fh:
        return yaml.safe_load(fh)


def centroid(geom: dict) -> tuple[float, float]:
    """Cheap polygon centroid — good enough to place a synthetic storm."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for k in c:
                walk(k)

    walk(geom["coordinates"])
    return sum(xs) / len(xs), sum(ys) / len(ys)


def band_for(score: float, bands: dict) -> str:
    for name, (lo, hi) in bands.items():
        if lo <= score < hi:
            return name
    return "critical"


def hhmm_to_minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def minutes_to_ist_str(total_min: int) -> str:
    """UTC minutes -> IST display string (charter R8: convert only for display)."""
    ist = (total_min + 330) % (24 * 60)
    return f"{ist // 60:02d}:{ist % 60:02d}"


# ------------------------------------------------------- the fake storm
def storm_intensity(t_min: int, peak_min: int = 7 * 60 + 30) -> float:
    """0..1 storm envelope: builds to `peak_min`, decays after."""
    spread = 150.0
    return math.exp(-((t_min - peak_min) ** 2) / (2 * spread**2))


def ward_susceptibility(lon: float, lat: float, name: str, hotspots: list[str]) -> float:
    """
    Fake 'terrain susceptibility'. Real InundaNet replaces this entirely.
    Central Delhi (the Yamuna trough) scores higher; named hotspots score
    highest so the demo storyline is visible from day one.
    """
    if name.upper() in hotspots:
        return 0.92
    d = math.hypot(lon - 77.23, lat - 28.64)          # distance from centre
    base = max(0.05, 1.0 - d * 6.0)
    return min(0.85, base * random.uniform(0.75, 1.15))


# ------------------------------------------------------------- writers
def build_wards(features: list[dict], cfg: dict) -> list[dict]:
    """Attach stable ids + static fake exposure to each real ward polygon."""
    hotspots = [h.upper() for h in cfg["labels"]["hotspot_wards"]]
    bbox = cfg["bbox"]
    out = []
    for i, f in enumerate(features):
        name = (f["properties"].get("Ward_Name") or f"WARD {i}").strip()
        lon, lat = centroid(f["geometry"])
        if not (bbox["west"] <= lon <= bbox["east"] and bbox["south"] <= lat <= bbox["north"]):
            continue
        out.append(
            {
                "ward_id": f"W{i:03d}",
                "ward_no": f["properties"].get("Ward_No") or f"W{i:03d}",
                "name": name,
                "lon": lon,
                "lat": lat,
                "geometry": f["geometry"],
                "susceptibility": ward_susceptibility(lon, lat, name, hotspots),
                # fake exposure — Phase 2 features/exposure.py replaces this
                "people": random.randint(8_000, 65_000),
                "hospitals": random.choice([0, 0, 1, 1, 2, 3]),
                "schools": random.randint(0, 9),
                "road_km": round(random.uniform(1.5, 14.0), 1),
                "pumps": random.choice([0, 0, 1, 2]),
            }
        )
    return out


DRIVER_POOL = [
    "low HAND",
    "impervious surface",
    "antecedent rain",
    "distance to drain",
    "low slope",
    "high flow accumulation",
]


def write_event(event: dict, wards: list[dict], cfg: dict) -> int:
    ev_id = event["id"]
    ev_dir = OUTPUTS / ev_id
    if ev_dir.exists():
        shutil.rmtree(ev_dir)
    (ev_dir / "frames").mkdir(parents=True, exist_ok=True)

    stamps = event["demo_timestamps"]
    bands = {k: tuple(v) for k, v in cfg["risk_bands"].items()}
    lat0 = cfg["rain_lattice"]["lat_start"]
    lon0 = cfg["rain_lattice"]["lon_start"]
    nlat = cfg["rain_lattice"]["lat_count"]
    nlon = cfg["rain_lattice"]["lon_count"]
    res = cfg["rain_lattice"]["resolution_deg"]
    thr = cfg["thresholds"]["forecast_24h_mm"]

    advisories_written = 0

    for stamp in stamps:
        t_min = hhmm_to_minutes(stamp)
        inten = storm_intensity(t_min)

        # ---------------------------------------------------- wards_*.geojson
        feats = []
        total_exposed = 0
        for w in wards:
            p = min(0.97, w["susceptibility"] * inten * random.uniform(0.85, 1.1))
            score = min(0.99, p * (0.6 + 0.4 * min(1.0, w["people"] / 50_000)))
            bandname = band_for(score, bands)
            crossing = p > 0.5
            onset = minutes_to_ist_str(t_min + 90) if crossing else None
            peak = minutes_to_ist_str(t_min + 135) if crossing else None
            ci90 = (
                [minutes_to_ist_str(t_min + 70), minutes_to_ist_str(t_min + 160)]
                if crossing
                else None
            )
            drivers = random.sample(DRIVER_POOL, 3)
            weights = sorted([round(random.uniform(0.08, 0.34), 2) for _ in range(3)], reverse=True)
            if p > 0.5:
                total_exposed += w["people"]

            feats.append(
                {
                    "type": "Feature",
                    "geometry": w["geometry"],
                    "properties": {
                        "ward_id": w["ward_id"],
                        "name": w["name"],
                        "p_flood": round(p, 3),
                        "onset": onset,
                        "peak": peak,
                        "ci90": ci90,
                        "people": w["people"],
                        "hospitals": w["hospitals"],
                        "schools": w["schools"],
                        "road_km": w["road_km"],
                        "pumps": w["pumps"],
                        "drivers": [[d, wt] for d, wt in zip(drivers, weights)],
                        "risk_score": round(score, 3),
                        "risk_band": bandname,
                    },
                }
            )

        (ev_dir / f"wards_{stamp}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats})
        )

        # ------------------------------------------------- rain_grid_*.json
        cells = []
        for i in range(nlat):
            for j in range(nlon):
                lat = round(lat0 + i * res, 2)
                lon = round(lon0 + j * res, 2)
                d = math.hypot(lon - 77.20, lat - 28.65)
                local = inten * max(0.1, 1.0 - d * 2.5)
                q50 = round(local * random.uniform(20, 45), 1)
                cells.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "p15": round(min(0.98, local * random.uniform(0.7, 1.05)), 3),
                        "p50": round(min(0.92, local * random.uniform(0.3, 0.6)), 3),
                        "q10": round(q50 * 0.35, 1),
                        "q50": q50,
                        "q90": round(q50 * 2.1, 1),
                    }
                )

        (ev_dir / f"rain_grid_{stamp}.json").write_text(
            json.dumps(
                {
                    "kind": "nowcast",
                    "lead_h": 3,
                    "cells": cells,
                    "forecast": {
                        "lead_h": 24,
                        "thresholds": {
                            str(thr["heavy"]): round(min(0.95, inten * 0.75), 2),
                            str(thr["very_heavy"]): round(min(0.6, inten * 0.28), 2),
                            str(thr["extremely_heavy"]): round(min(0.2, inten * 0.05), 2),
                        },
                    },
                }
            )
        )

        # ------------------------------------------------------- kpi_*.json
        crit = [f for f in feats if f["properties"]["risk_band"] == "critical"]
        city_risk = (
            "CRITICAL" if len(crit) > 12 else
            "HIGH" if len(crit) > 4 else
            "WATCH" if inten > 0.3 else "LOW"
        )
        (ev_dir / f"kpi_{stamp}.json").write_text(
            json.dumps(
                {
                    "rain_now_mm_h": round(inten * 42, 1),
                    "p3h50": round(min(0.95, inten * 0.8), 2),
                    "city_risk": city_risk,
                    "time_to_critical_min": max(10, int(180 * (1 - inten))) if inten > 0.2 else None,
                    "people_exposed": total_exposed,
                    "badges": {
                        "sat": "ok",
                        "radar": "ok",
                        "stations": "degraded",
                        "nwp": "ok",
                    },
                }
            )
        )

        # ------------------------------------------- advisory_{ward}_*.json
        for f in sorted(feats, key=lambda x: -x["properties"]["risk_score"])[:5]:
            p = f["properties"]
            (ev_dir / f"advisory_{p['ward_id']}_{stamp}.json").write_text(
                json.dumps(
                    {
                        "advisory_en": (
                            f"[FAKE] {p['name']}: flood probability {p['p_flood']:.0%}"
                            f"{', water expected by ' + p['onset'] if p['onset'] else ''}. "
                            f"About {p['people']:,} residents, {p['hospitals']} hospital(s) and "
                            f"{p['schools']} school(s) are in the exposed area. Main drivers: "
                            f"{', '.join(d for d, _ in p['drivers'])}."
                        ),
                        "advisory_hi": (
                            f"[FAKE] {p['name']}: बाढ़ की संभावना {p['p_flood']:.0%}। "
                            f"लगभग {p['people']:,} निवासी प्रभावित हो सकते हैं।"
                        ),
                        "actions": [
                            f"Deploy pump teams to {p['name']} low points",
                            f"Alert {p['hospitals']} hospital(s) on access routes",
                            "Position traffic diversion at the underpass",
                        ],
                        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                        "cached": True,
                    },
                    ensure_ascii=False,
                )
            )
            advisories_written += 1

    return advisories_written


def write_metrics_stub() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "metrics.json").write_text(
        json.dumps(
            {
                "reliability": {
                    "raincast_15mm": [
                        {"bin_center": b, "predicted": b,
                         "observed": round(min(1.0, max(0.0, b + (0.05 - 0.1 * b))), 3),
                         "count": 200}
                        for b in [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
                    ]
                },
                "ablation": [
                    {"config": "[FAKE] all sources", "csi": 0.41, "pod": 0.62, "far": 0.38, "brier": 0.081},
                    {"config": "[FAKE] no satellite", "csi": 0.35, "pod": 0.54, "far": 0.43, "brier": 0.094},
                    {"config": "[FAKE] no NWP", "csi": 0.33, "pod": 0.51, "far": 0.45, "brier": 0.099},
                    {"config": "[FAKE] raw ECMWF", "csi": 0.27, "pod": 0.44, "far": 0.52, "brier": 0.118},
                ],
                "skill_vs_lead": [
                    {"lead_h": h, "csi": round(0.52 * math.exp(-h / 4.5), 3), "model": "RainCast"}
                    for h in [1, 2, 3, 6]
                ],
                "leadtime_vs_cap": [
                    {
                        "event": "2024-06-28",
                        "pravaah_crossing_utc": "2024-06-28T00:30Z",
                        "imd_cap_sent_utc": "2024-06-28T01:45Z",
                        "minutes_gained": 75.0,
                        "matched_far": 0.38,
                    }
                ],
                "notes": {"status": "FAKE PLACEHOLDER — replaced in Phase 13"},
            },
            indent=2,
        )
    )


def validate() -> bool:
    """Validate what we just wrote against serve/schemas.py. Optional but loud."""
    try:
        sys.path.insert(0, str(ROOT))
        from serve.schemas import Advisory, Kpi, Metrics, OutputsIndex, RainGrid, WardsFeatureCollection
    except Exception as exc:  # noqa: BLE001
        print(f"  !  skipped validation (pydantic/schemas unavailable: {exc})")
        return True

    OutputsIndex.model_validate(json.loads((OUTPUTS / "index.json").read_text()))
    n = 0
    for ev_dir in OUTPUTS.iterdir():
        if not ev_dir.is_dir():
            continue
        for p in ev_dir.glob("wards_*.geojson"):
            WardsFeatureCollection.model_validate(json.loads(p.read_text())); n += 1
        for p in ev_dir.glob("rain_grid_*.json"):
            RainGrid.model_validate(json.loads(p.read_text())); n += 1
        for p in ev_dir.glob("kpi_*.json"):
            Kpi.model_validate(json.loads(p.read_text())); n += 1
        for p in ev_dir.glob("advisory_*.json"):
            Advisory.model_validate(json.loads(p.read_text())); n += 1
    Metrics.model_validate(json.loads((REPORTS / "metrics.json").read_text()))
    print(f"  OK  {n + 2} files validated against serve/schemas.py")
    return True


def main() -> int:
    if not WARDS_RAW.exists():
        print(f"FATAL: {WARDS_RAW} missing. Fetch the DataMeet ward file first.")
        return 1

    cfg = load_config()
    raw = json.loads(WARDS_RAW.read_text())
    wards = build_wards(raw["features"], cfg)
    print(f"  wards in AOI: {len(wards)} / {len(raw['features'])}")

    hotspots = [h.upper() for h in cfg["labels"]["hotspot_wards"]]
    found = [w["name"] for w in wards if w["name"].upper() in hotspots]
    print(f"  hotspot wards present: {found}")

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    index_events = []
    for event in cfg["events"]:
        if not event.get("demo_timestamps"):
            continue
        n_adv = write_event(event, wards, cfg)
        index_events.append(
            {
                "id": event["id"],
                "name": event["name"],
                "timestamps": event["demo_timestamps"],
                "wards": len(wards),
            }
        )
        print(f"  wrote event {event['id']}: "
              f"{len(event['demo_timestamps'])} timestamps, {n_adv} advisories")

    (OUTPUTS / "index.json").write_text(
        json.dumps({"events": index_events, "schema": 3}, indent=2)
    )
    write_metrics_stub()
    validate()
    print(f"\n  FAKES READY -> {OUTPUTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
