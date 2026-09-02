"""
PRAVAAH — the what-if sandbox. LIVE InundaNet inference on synthetic rain.

WHY THIS BREAKS THE PACKAGE'S OWN RULE, DELIBERATELY
----------------------------------------------------
serve/main.py opens with "if you find yourself importing lightgbm in this
package, stop." That rule exists so the serving layer stays a reader of frozen
artefacts and never quietly becomes a training environment — it is what keeps
the ML side and the app side independently replaceable.

The sandbox is the one honest exception, and it is scoped rather than waived:

  * The input space is CONTINUOUS. A judge dragging a rainfall slider cannot be
    served from precomputed frames without either quantising the sliders into a
    lie or shipping a combinatorial artefact.
  * It loads the SHIPPED artefact, models/inundanet_v0.txt — the same bytes the
    replay used. It cannot fit, refit or write a model. There is no training
    code path in this file.
  * It is imported LAZILY, inside the endpoint. If lightgbm is missing or the
    artefact is absent, every other route still serves.

So the guarantee the rule was protecting still holds: nothing here can change a
number that /replay or /verify reports.

WHAT IS SYNTHETIC AND WHAT IS REAL — SAY IT PLAINLY
---------------------------------------------------
Synthetic: the four rain inputs, which the user chooses.
Real:      the 13 static terrain features per cell (HAND, TWI, imperviousness,
           drain distance, underpass density, ...), the 148,776-cell 100 m grid,
           the ward geometry, the exposure counts, and the trained model.

That split is the entire point of the feature. It is not a mock screen with
invented output — it is the real model, on real terrain, answering a question
the user invented. So the honest label is "hypothetical rainfall", never
"forecast", and the response carries `is_forecast: false` so no client can
render it as one.

WHY THE SLIDERS BEHAVE
----------------------
InundaNet was trained with monotone_constraints on all four rain features, so
raising rain can only raise a cell's probability, never lower it. That was added
because a replay once showed risk FALLING at the storm peak. Here it pays a
second dividend: the sandbox cannot embarrass us with a non-monotone answer in
front of judges, and "more rain never means less risk" is a property we can
state as a guarantee rather than a hope.

STORM PLACEMENT
---------------
Rain may be uniform over the city, or placed as a Gaussian cell at a chosen
lat/lon with a radius. Placement is what makes the demo persuasive: it lets a
judge put the burst over a ward they know and watch whether the model's answer
matches their own knowledge of where Delhi floods. The kernel is a plain
Gaussian — a stated, simple shape, not a pretend storm model.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cube" / "sandbox_cells.parquet"
MODEL = ROOT / "models" / "inundanet_v0.txt"
EXPOSURE = ROOT / "data" / "static" / "exposure.parquet"

RAIN_COLS = ["rain_sum", "rain_max", "rain_prev3d", "rain_prev7d"]

# Peak-hour share of a 6 h burst, used only when sweeping the response curve.
# Must stay above 1/6, or the swept storm is physically impossible.
PEAK_SHARE = 0.28

# UNITS MATTER HERE, AND THEY ARE NOT IMD'S UNITS.
#
# `rain_sum` is a 6 HOUR ERA5 accumulation — the same quantity precompute feeds
# the model — while IMD's famous 64.5 / 115.6 / 204.5 mm categories are 24 HOUR
# gauge totals. The two are not interchangeable, and ERA5 additionally smooths
# convective peaks downward (28 Jun 2024: ERA5 20.9 mm where IMD's grid said
# 150.7 mm).
#
# So presets built from IMD's daily thresholds would all land far past the
# model's evidence limit and every one of them would return the same answer. The
# presets below are spaced across the range the model can actually discriminate,
# and the last one is deliberately past the limit to DEMONSTRATE saturation
# rather than hide it.
PRESETS = [
    {"id": "light", "label": "Light shower", "rain_sum": 5, "rain_max": 2,
     "rain_prev3d": 5, "rain_prev7d": 15,
     "note": "A wet evening. Most wards stay low."},
    {"id": "moderate", "label": "Moderate spell", "rain_sum": 12, "rain_max": 4,
     "rain_prev3d": 15, "rain_prev7d": 30,
     "note": "Routine monsoon rain over six hours."},
    {"id": "heavy", "label": "Heavy burst", "rain_sum": 20, "rain_max": 7,
     "rain_prev3d": 25, "rain_prev7d": 45,
     "note": "The blackspots begin to separate from the rest of the city."},
    {"id": "limit", "label": "Edge of evidence", "rain_sum": 25, "rain_max": 12,
     "rain_prev3d": 40, "rain_prev7d": 70,
     "note": "The wettest conditions the flood labels actually contain."},
    # Differs from "limit" in rain_sum ONLY, so the flatness is attributable. A
    # preset that moved four sliders at once would read as a dramatic jump
    # rather than as a demonstration.
    #
    # 40 mm rather than a showier 120 mm, because the physical constraint
    # rain_sum/6 <= rain_max <= rain_sum has to hold for BOTH members of the
    # pair: a 6 h total of 120 mm forces rain_max >= 20, which would have moved
    # a second slider and ruined the isolation. 40 mm makes the same point — it
    # already returns exactly what 300 mm returns.
    {"id": "beyond", "label": "Beyond evidence (saturates)", "rain_sum": 40,
     "rain_max": 12, "rain_prev3d": 40, "rain_prev7d": 70,
     "note": ("Only rain_sum changed, 25 -> 40 mm. Every value above the "
              "evidence limit returns this same answer — 40 mm, 120 mm and "
              "300 mm are identical. Shown on purpose: a model that cannot say "
              "more should not pretend to.")},
]


@lru_cache(maxsize=1)
def _load():
    """Cells, model and exposure. Cached — the frame is 148k rows."""
    import lightgbm as lgb                      # lazy: see module docstring
    cells = pd.read_parquet(CELLS)
    booster = lgb.Booster(model_file=str(MODEL))
    exp = pd.read_parquet(EXPOSURE)
    if "geometry" in exp.columns:
        exp = exp.drop(columns=["geometry"])
    return cells, booster, exp


def available() -> bool:
    return CELLS.exists() and MODEL.exists()


@lru_cache(maxsize=1)
def _bands() -> dict:
    """
    Risk bands from the AOI config — the SAME cut points precompute uses.

    Hardcoding them here would let the sandbox and the replay drift apart and
    disagree about what "high" means, which is exactly the kind of quiet
    inconsistency a judge would find. The literal is only a fallback if the
    config is unreadable.
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "configs" / "aoi_delhi_ncr.yaml").read_text())
        return {k: tuple(v) for k, v in cfg["risk_bands"].items()}
    except Exception:
        return {"low": (0, 0.35), "watch": (0.35, 0.6),
                "high": (0.6, 0.8), "critical": (0.8, 1.01)}


@lru_cache(maxsize=1)
def evidence_bounds() -> dict:
    """
    The largest split threshold the trained model uses on each rain feature.

    THIS IS THE MOST IMPORTANT NUMBER IN THE SANDBOX, so it is read out of the
    artefact rather than written down. A gradient-boosted tree is a step
    function: above its highest split on a feature it is mathematically CONSTANT
    in that feature. For rain_sum that boundary is ~25 mm, because the flood
    labels simply do not contain 6 h ERA5 accumulations above it.

    So a 0-300 mm slider would be a control that does nothing over 90% of its
    travel. Rather than cap the slider and hide that, the UI draws the response
    curve and marks this boundary: "beyond here the model has no training
    evidence and its answer stops changing." Showing where a model runs out of
    evidence is worth more to a technical audience than a slider that appears to
    work.

    Note this is NOT fixable by quantile-mapping the inputs. Quantile mapping is
    monotone, trees split on order, so a mapped model is the identical tree with
    rescaled thresholds. The bias-correction work targets RainCast, where the
    compressed quantity is the TARGET and a rescale genuinely changes which
    hours count as positives.
    """
    import lightgbm as lgb
    b = lgb.Booster(model_file=str(MODEL))
    names = b.feature_name()
    hi: dict[str, float] = {}

    def walk(n):
        if "split_index" in n:
            f = names[n["split_feature"]]
            if f in RAIN_COLS:
                hi[f] = max(hi.get(f, 0.0), float(n["threshold"]))
            walk(n["left_child"])
            walk(n["right_child"])

    for t in b.dump_model()["tree_info"]:
        walk(t["tree_structure"])
    return {c: round(hi.get(c, 0.0), 2) for c in RAIN_COLS}


def response_curve(rain_prev3d: float = 25.0, rain_prev7d: float = 45.0,
                   n: int = 24, hi: float = 120.0) -> dict:
    """
    City-max flood probability as a function of event rainfall.

    Drawn in the UI beside the sliders so the flattening is visible, not merely
    asserted. Uses the same 90th-percentile ward rule as everything else.
    """
    cells, booster, exp = _load()
    feats = booster.feature_name()
    df = cells.copy()
    for c in feats:
        if c not in df:
            df[c] = np.nan
    df["rain_prev3d"] = rain_prev3d
    df["rain_prev7d"] = rain_prev7d

    pts = []
    for r in np.linspace(0, hi, n):
        df["rain_sum"] = r
        df["rain_max"] = r * PEAK_SHARE
        p = booster.predict(df[feats])
        s = pd.Series(p).groupby(df["ward_no"].to_numpy()).quantile(0.90)
        pts.append({"rain_mm": round(float(r), 1),
                    "max_p": round(float(s.max()), 4),
                    "wards_over_60pct": int((s >= 0.60).sum())})

    # BE EXPLICIT THAT TWO FEATURES ARE MOVING.
    #
    # The sweep raises rain_max alongside rain_sum, because holding the peak
    # hour fixed while the 6 h total climbs to 120 mm would plot a storm that
    # cannot exist (rain_max >= rain_sum/6). The cost is that the curve is NOT
    # purely rain_sum's response: it takes a second step when rain_max crosses
    # its own limit, which a reader would otherwise misread as the model still
    # responding to the total.
    #
    # So the API names both boundaries rather than leaving the UI to explain a
    # step the payload does not account for.
    b = evidence_bounds()
    return {
        "points": pts,
        "evidence_limit_mm": b["rain_sum"],
        "swept": {
            "rain_sum": "x axis",
            "rain_max": f"{PEAK_SHARE} x rain_sum, to keep the storm physical",
        },
        "second_step_mm": round(b["rain_max"] / PEAK_SHARE, 1),
        "note": ("Above the evidence limit the curve is flat because the model "
                 "has no training examples there, not because more rain is "
                 "harmless. One further step appears near second_step_mm, where "
                 "the swept rain_max crosses ITS own limit "
                 f"({b['rain_max']} mm) — that step is the peak-hour feature, "
                 "not the 6 h total."),
    }


def _weights(cells: pd.DataFrame, lat, lon, radius_km) -> np.ndarray:
    """Gaussian storm kernel, or uniform ones when no centre is given."""
    if lat is None or lon is None:
        return np.ones(len(cells))
    # Local equirectangular approximation — over a 50 km box the error is far
    # below the 100 m cell size, so a great-circle distance would be false
    # precision.
    dy = (cells["lat"].to_numpy() - float(lat)) * 111.0
    dx = ((cells["lon"].to_numpy() - float(lon)) * 111.0
          * math.cos(math.radians(float(lat))))
    d = np.hypot(dx, dy)
    sigma = max(float(radius_km), 1.0) / 2.0        # radius ~ 2 sigma
    return np.exp(-0.5 * (d / sigma) ** 2)


def run(rain_sum: float, rain_max: float, rain_prev3d: float,
        rain_prev7d: float, lat=None, lon=None, radius_km: float = 12.0,
        bands: dict | None = None) -> dict:
    """
    Predict ward flood probability under user-chosen rainfall.

    Ward probability is the 90th percentile of its cells — the SAME rule
    precompute uses. A ward floods when its worst pockets flood, and a mean
    would dilute a real underpass hazard into a large dry ward. Using a
    different rule here would make the sandbox disagree with the replay for a
    reason that has nothing to do with the rain.
    """
    cells, booster, exp = _load()
    feats = booster.feature_name()
    bounds = evidence_bounds()

    w = _weights(cells, lat, lon, radius_km)
    df = cells.copy()
    # Antecedent rain is regional and does not follow the burst, so only the
    # event-rain features are shaped by the kernel. Weighting the 7-day total by
    # the storm footprint would imply the past week's rain fell in the same spot.
    df["rain_sum"] = rain_sum * w
    df["rain_max"] = rain_max * w
    df["rain_prev3d"] = rain_prev3d
    df["rain_prev7d"] = rain_prev7d
    for c in feats:
        if c not in df:
            df[c] = np.nan

    df["p"] = booster.predict(df[feats])

    agg = (df.groupby(["ward_no", "ward_name"], as_index=False)
             .agg(p_flood=("p", lambda s: float(np.percentile(s, 90))),
                  rain_here=("rain_sum", "mean"),
                  n_cells=("p", "size")))
    agg = agg.merge(exp, on=["ward_no", "ward_name"], how="left")

    pop = agg["population"].fillna(0)
    pop_norm = pop / max(pop.max(), 1)
    agg["risk_score"] = (agg.p_flood * (0.65 + 0.35 * pop_norm)).clip(0, 0.999)

    bands = bands or _bands()

    def band_for(s: float) -> str:
        for name, (lo, hi) in bands.items():
            if lo <= s < hi:
                return name
        return "critical"

    agg["risk_band"] = agg.risk_score.map(band_for)

    # Drivers for the single most-at-risk ward. SHAP on the same rows, so the
    # explanation is of THIS prediction, not a generic feature-importance chart.
    top_ward = agg.sort_values("risk_score", ascending=False).iloc[0]
    sub = df[df.ward_no == top_ward.ward_no]
    contrib = booster.predict(sub[feats], pred_contrib=True)
    cm = pd.Series(contrib[:, :-1].mean(axis=0), index=feats)
    drivers = [{"feature": k, "contribution": round(float(v), 4)}
               for k, v in cm.sort_values(ascending=False)[:5].items() if v > 0]

    counts = agg.risk_band.value_counts().to_dict()
    exposed = agg.loc[agg.risk_band.isin(["high", "critical"]), "population"]

    return {
        "is_forecast": False,
        "label": "HYPOTHETICAL — user-chosen rainfall, not a forecast",
        "units": {
            "rain_sum": "mm over 6 h (ERA5 scale)",
            "rain_max": "mm in the peak hour (ERA5 scale)",
            "rain_prev3d": "mm over the previous 3 days",
            "rain_prev7d": "mm over the previous 7 days",
            "caveat": ("These are 6 h ERA5 accumulations, NOT IMD's 24 h gauge "
                       "categories (64.5 / 115.6 / 204.5 mm). ERA5 also smooths "
                       "convective peaks down, so these numbers read lower than "
                       "a rain gauge would."),
        },
        "inputs": {"rain_sum": rain_sum, "rain_max": rain_max,
                   "rain_prev3d": rain_prev3d, "rain_prev7d": rain_prev7d,
                   "centre": None if lat is None else [float(lat), float(lon)],
                   "radius_km": radius_km if lat is not None else None},
        "wards": [
            {"ward_id": str(r.ward_no), "name": r.ward_name,
             "p_flood": round(float(r.p_flood), 3),
             "risk_score": round(float(r.risk_score), 3),
             "risk_band": r.risk_band,
             "rain_here_mm": round(float(r.rain_here), 1),
             "people": int(r.population or 0),
             "hospitals": int(getattr(r, "hospitals", 0) or 0),
             "schools": int(getattr(r, "schools", 0) or 0)}
            for r in agg.itertuples()
        ],
        "summary": {
            "bands": {k: int(v) for k, v in counts.items()},
            "wards_total": int(len(agg)),
            "people_exposed": int(exposed.fillna(0).sum()),
            "max_p_flood": round(float(agg.p_flood.max()), 3),
            "top_ward": {"name": top_ward.ward_name,
                         "ward_id": str(top_ward.ward_no),
                         "p_flood": round(float(top_ward.p_flood), 3),
                         "drivers": drivers},
        },
        "model": {
            "name": "InundaNet v0", "artefact": MODEL.name,
            "cells_scored": int(len(df)),
            "note": ("Live inference by the shipped model on real 100 m terrain. "
                     "Only the rainfall is user-chosen. Monotone constraints on "
                     "all four rain features mean more rain can never lower a "
                     "ward's probability."),
        },
        # Surfaced on every response so a client cannot render a slider that
        # silently does nothing. `saturated` is true when the user has pushed a
        # feature past the model's last split on it.
        "evidence": {
            "limits_mm": bounds,
            "saturated": {c: bool(v > bounds.get(c, 0.0))
                          for c, v in (("rain_sum", rain_sum),
                                       ("rain_max", rain_max),
                                       ("rain_prev3d", rain_prev3d),
                                       ("rain_prev7d", rain_prev7d))},
            "note": ("A gradient-boosted tree is constant above its highest "
                     "split on a feature. Past these values the model has no "
                     "training evidence and its answer stops changing — that is "
                     "a limit of the flood-label set, not a claim that heavier "
                     "rain is harmless."),
        },
        "presets": PRESETS,
    }


def build_cells() -> None:
    """
    Regenerate cube/sandbox_cells.parquet.

    The cache is the SAME 100 m cell frame precompute builds, minus geometry and
    plus lat/lon for storm placement. It is derived, so it must be reproducible
    from one command rather than existing only because someone once ran a
    snippet — the repo already tracks derived artefacts (cube, model), and an
    artefact nobody can rebuild is a liability at demo time.

        python -m serve.sandbox --build-cells
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    _sys.argv = ["build_cells"]
    from scripts.precompute import build_cell_frame, load_cfg

    cells = build_cell_frame(load_cfg())
    keep = ([c for c in cells.columns if c.startswith("st_")]
            + ["ward_no", "ward_name", "lat", "lon"])
    cells[keep].to_parquet(CELLS)
    print(f"  -> {CELLS.relative_to(ROOT)}  "
          f"{len(cells):,} cells, {cells.ward_no.nunique()} wards")


if __name__ == "__main__":
    import sys as _s
    if "--build-cells" in _s.argv:
        build_cells()
    else:
        print(__doc__)
        print("evidence limits:", evidence_bounds())
