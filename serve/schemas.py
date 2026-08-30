"""
PRAVAAH — the frozen file contracts, in machine-readable form.

This module is the SINGLE source of truth for the shape of every file in
data/outputs/. It mirrors PRAVAAH.md section 12.2 exactly.

RULES
-----
1. Do NOT change a schema unilaterally. Bump `SCHEMA_VERSION` and
   `index.json["schema"]`, and log it in BUILD_PLAN.md's Progress Log.
2. Every writer (scripts/make_fakes.py, scripts/precompute.py) must validate
   what it writes against these models.
3. Every reader (serve/main.py, ui-fallback/streamlit_app.py) may assume them.

The whole point: the app is built against fakes, the models later write real
files with the SAME shape, and nothing downstream changes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 3

RiskBand = Literal["low", "watch", "high", "critical"]
BadgeState = Literal["ok", "degraded", "down"]
RainKind = Literal["nowcast", "forecast"]


# --------------------------------------------------------------- index.json
class EventInfo(BaseModel):
    id: str                              # "2024-06-28"
    name: str                            # "Delhi cloudburst 28 Jun 2024"
    timestamps: list[str]                # ["0400", "0430", ...] UTC HHMM
    wards: int


class OutputsIndex(BaseModel):
    events: list[EventInfo]
    schema_: int = Field(SCHEMA_VERSION, alias="schema")

    model_config = {"populate_by_name": True}


# ------------------------------------ {event}/wards_{HHMM}.geojson properties
class WardProperties(BaseModel):
    ward_id: str                         # "W047"
    name: str                            # "MINTO ROAD"
    p_flood: float = Field(ge=0.0, le=1.0)
    onset: str | None                    # "06:30" IST display, None if no crossing
    peak: str | None                     # "07:15"
    ci90: list[str] | None               # ["06:40", "07:50"] — 90% interval
    people: int
    hospitals: int
    schools: int
    road_km: float
    pumps: int
    # SHAP top-3, already translated to plain words: [["low HAND", 0.31], ...]
    drivers: list[tuple[str, float]]
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_band: RiskBand


class WardFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: WardProperties


class WardsFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[WardFeature]


# ---------------------------------------- {event}/rain_grid_{HHMM}.json
class RainCell(BaseModel):
    lat: float
    lon: float
    p15: float = Field(ge=0.0, le=1.0)   # P(>15 mm)  — the guaranteed head
    p50: float = Field(ge=0.0, le=1.0)   # P(>50 mm)
    q10: float                           # mm, quantile forecasts
    q50: float
    q90: float


class ForecastBlock(BaseModel):
    lead_h: int
    # keys are the official IMD categories as strings: "64.5" | "115.6" | "204.5"
    thresholds: dict[str, float]


class RainGrid(BaseModel):
    kind: RainKind
    lead_h: int
    cells: list[RainCell]
    forecast: ForecastBlock | None = None


# --------------------------------------------- {event}/kpi_{HHMM}.json
class Badges(BaseModel):
    sat: BadgeState
    radar: BadgeState
    stations: BadgeState
    nwp: BadgeState


class Kpi(BaseModel):
    rain_now_mm_h: float
    p3h50: float = Field(ge=0.0, le=1.0)
    city_risk: Literal["LOW", "WATCH", "HIGH", "CRITICAL"]
    time_to_critical_min: int | None     # None = no crossing predicted
    people_exposed: int
    badges: Badges


# ------------------------------ {event}/advisory_{ward}_{HHMM}.json
class Advisory(BaseModel):
    advisory_en: str
    advisory_hi: str
    actions: list[str] = Field(min_length=3, max_length=3)
    generated: str                       # ISO8601 UTC
    cached: bool


# ------------------------------------------------- reports/metrics.json
class ReliabilityPoint(BaseModel):
    bin_center: float
    predicted: float
    observed: float
    count: int


class AblationRow(BaseModel):
    config: str                          # "all sources" | "no satellite" | "raw ECMWF"
    csi: float
    pod: float
    far: float
    brier: float


class SkillPoint(BaseModel):
    lead_h: float
    csi: float
    model: str


class LeadTimeRow(BaseModel):
    event: str
    pravaah_crossing_utc: str
    imd_cap_sent_utc: str
    minutes_gained: float
    matched_far: float


class Metrics(BaseModel):
    """Consumed by GET /api/verify/metrics — this IS the four-proofs payload."""
    reliability: dict[str, list[ReliabilityPoint]]   # keyed by model head
    ablation: list[AblationRow]                      # Proof P-1
    skill_vs_lead: list[SkillPoint]
    leadtime_vs_cap: list[LeadTimeRow]               # Proof P-3
    notes: dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------ health
class Health(BaseModel):
    badges: Badges
    feeds: dict[str, str]                # feed name -> ISO timestamp of newest file
    ok: bool
