"""
PRAVAAH backend — FastAPI over precomputed files (BUILD_PLAN P10).

PHILOSOPHY (PRAVAAH.md §10.1)
----------------------------
The models NEVER run here. Every number the demo shows was precomputed into
data/outputs/ and committed. This module is a thin file reader.

    If you find yourself importing lightgbm in this package, stop.
    Something has gone wrong.

Replay is just the clock: every endpoint filters to artefacts stamped <= t.
Because those artefacts were generated through the cube's latest-at-t0
accessor, replay automatically shows only what was knowable at that moment.
The same honesty law (charter R4), enforced end to end.

    uvicorn serve.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = Path(os.getenv("PRAVAAH_OUTPUTS", ROOT / "data" / "outputs"))
REPORTS = ROOT / "reports"
UI_DIST = ROOT / "ui" / "dist"

app = FastAPI(
    title="PRAVAAH",
    description="Heavy-rainfall nowcast + inundation prediction. Serves precomputed artefacts.",
    version="0.1.0",
)


# --------------------------------------------------------------- helpers
def _read(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"not found: {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"corrupt artefact {path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def _index() -> dict:
    return _read(OUTPUTS / "index.json")


def _timestamps(event: str) -> list[str]:
    for ev in _index()["events"]:
        if ev["id"] == event:
            return ev["timestamps"]
    raise HTTPException(status_code=404, detail=f"unknown event: {event}")


def _resolve_t(event: str, t: str | None) -> str:
    """
    THE REPLAY LAW: return the latest available timestamp <= t.

    Never returns something stamped after the clock. If t falls between two
    artefacts we serve the earlier one — the future has not happened yet.
    """
    stamps = _timestamps(event)
    if t is None:
        return stamps[0]
    eligible = [s for s in stamps if s <= t]
    if not eligible:
        raise HTTPException(
            status_code=404,
            detail=f"no artefact issued at or before {t} for event {event}",
        )
    return max(eligible)


# ---------------------------------------------------------------- routes
@app.get("/api/events")
def get_events() -> dict:
    """Curated event list + the timestamps available for each."""
    return _index()


@app.get("/api/state")
def get_state(event: str, t: str | None = Query(None)) -> dict:
    """City-level KPIs at clock t."""
    ts = _resolve_t(event, t)
    return {"event": event, "t": ts, **_read(OUTPUTS / event / f"kpi_{ts}.json")}


@app.get("/api/wards")
def get_wards(event: str, t: str | None = Query(None)) -> dict:
    """Ward GeoJSON with p_flood, onset, drivers, exposure, risk."""
    ts = _resolve_t(event, t)
    return _read(OUTPUTS / event / f"wards_{ts}.geojson")


@app.get("/api/rain")
def get_rain(
    event: str,
    t: str | None = Query(None),
    kind: str = Query("nowcast", pattern="^(nowcast|forecast)$"),
    lead: int | None = Query(None),
) -> dict:
    """Rain probability grid with quantiles."""
    ts = _resolve_t(event, t)
    grid = _read(OUTPUTS / event / f"rain_grid_{ts}.json")
    grid["kind"] = kind
    if lead is not None:
        grid["lead_h"] = lead
    return grid


@app.get("/api/ward/{ward_id}")
def get_ward(ward_id: str, event: str, t: str | None = Query(None)) -> dict:
    """
    Single-ward detail + its probability timeline.

    The timeline is assembled across every timestamp <= t, so the chart shows
    the ward's history as it was known at the clock — never the full event.
    """
    ts = _resolve_t(event, t)
    fc = _read(OUTPUTS / event / f"wards_{ts}.geojson")
    match = next(
        (f for f in fc["features"] if f["properties"]["ward_id"] == ward_id), None
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown ward: {ward_id}")

    timeline = []
    for stamp in [s for s in _timestamps(event) if s <= ts]:
        path = OUTPUTS / event / f"wards_{stamp}.geojson"
        if not path.exists():
            continue
        prior = json.loads(path.read_text())
        hit = next(
            (f for f in prior["features"] if f["properties"]["ward_id"] == ward_id), None
        )
        if hit:
            timeline.append(
                {
                    "t": stamp,
                    "p_flood": hit["properties"]["p_flood"],
                    "risk_score": hit["properties"]["risk_score"],
                }
            )

    return {"event": event, "t": ts, "feature": match, "timeline": timeline}


@app.get("/api/frames")
def get_frames(event: str, t: str | None = Query(None)) -> dict:
    """pySTEPS / radar animation frame URLs available at or before t."""
    ts = _resolve_t(event, t)
    frames_dir = OUTPUTS / event / "frames"
    frames = (
        sorted(f.name for f in frames_dir.glob("*.png") if f.stem.split("_")[-1] <= ts)
        if frames_dir.exists()
        else []
    )
    return {
        "event": event,
        "t": ts,
        "frames": [f"/static/{event}/frames/{n}" for n in frames],
    }


@app.post("/api/advisory/{ward_id}")
def post_advisory(ward_id: str, event: str, t: str | None = Query(None)) -> dict:
    """
    Bilingual ward advisory. CACHE-FIRST — the demo never blocks on an LLM.

    Cache hit  -> return it.
    Cache miss -> return the structured numbers with narration_available=False.
                  Live regeneration (§13) is wired in P10-T6; it must never
                  become a hard dependency of this endpoint.
    """
    ts = _resolve_t(event, t)
    cached = OUTPUTS / event / f"advisory_{ward_id}_{ts}.json"
    if cached.exists():
        return _read(cached)

    fc = _read(OUTPUTS / event / f"wards_{ts}.geojson")
    match = next(
        (f for f in fc["features"] if f["properties"]["ward_id"] == ward_id), None
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown ward: {ward_id}")

    # Cache miss. Generate on the spot — serve.advisory falls back to a
    # deterministic bilingual renderer that needs no key and no network, so this
    # path cannot fail and cannot invent a number (see serve/advisory.py).
    try:
        from serve.advisory import generate
        adv = generate(match["properties"], event)
        adv["cached"] = False
        return adv
    except Exception as exc:  # noqa: BLE001 — narration never breaks the endpoint
        return {
            "narration_available": False,
            "note": f"narration unavailable ({type(exc).__name__}) — model numbers only",
            "properties": match["properties"],
        }


@app.get("/api/verify/metrics")
def get_metrics() -> dict:
    """The four-proofs payload: reliability, ablation, skill-vs-lead, lead-time."""
    return _read(REPORTS / "metrics.json")


@app.get("/api/health")
def get_health() -> dict:
    """Logger freshness + which sources feed the current view (the UI badges)."""
    try:
        idx = _index()
        events = [e["id"] for e in idx["events"]]
        ok = True
    except HTTPException:
        events, ok = [], False

    return {
        "ok": ok,
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outputs_dir": str(OUTPUTS.relative_to(ROOT)) if OUTPUTS.is_relative_to(ROOT) else str(OUTPUTS),
        "events": events,
        "ui_built": UI_DIST.exists(),
        "badges": {"sat": "ok", "radar": "ok", "stations": "degraded", "nwp": "ok"},
    }


@app.exception_handler(404)
async def not_found(_request, exc):  # noqa: ANN001, ANN201
    return JSONResponse(status_code=404, content={"detail": str(exc.detail)})


# ------------------------------------------------------- static mounting
# MUST be last: StaticFiles at "/" swallows every route registered after it.
# html=True makes client-side routes (/command, /inundation) fall back to
# index.html instead of 404-ing on refresh.
def _mount_static() -> None:
    from fastapi.staticfiles import StaticFiles

    if OUTPUTS.exists():
        app.mount("/static", StaticFiles(directory=OUTPUTS), name="outputs")
    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    else:
        @app.get("/")
        def _dev_root() -> dict:
            return {
                "service": "PRAVAAH",
                "ui": "not built yet — run `cd ui && npm run build`, or use the Vite dev server",
                "docs": "/docs",
                "health": "/api/health",
            }


_mount_static()
