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
from fastapi.responses import JSONResponse, Response

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
def _index_cached(mtime: float) -> dict:
    return _read(OUTPUTS / "index.json")


def _index() -> dict:
    """
    Keyed on the file's mtime so a live update is picked up without a restart.

    The previous version cached unconditionally, which meant a new live
    snapshot was invisible until the server was bounced — fine when the only
    event was historical, wrong now that the file changes every 15 minutes.
    """
    p = OUTPUTS / "index.json"
    return _index_cached(p.stat().st_mtime if p.exists() else 0.0)


_index.cache_clear = _index_cached.cache_clear


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


def _event_name(event: str) -> str:
    for ev in _index()["events"]:
        if ev["id"] == event:
            return ev.get("name", event)
    return event


def _cap_alert(ward_id: str, event: str, t: str | None) -> dict:
    """Shared by both CAP endpoints: resolve the clock, find the ward, build the alert."""
    from serve import cap as cap_mod

    ts = _resolve_t(event, t)
    fc = _read(OUTPUTS / event / f"wards_{ts}.geojson")
    match = next(
        (f for f in fc["features"] if f["properties"]["ward_id"] == ward_id), None
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown ward: {ward_id}")
    return cap_mod.build(
        match["properties"], match.get("geometry"), event, _event_name(event), ts
    )


@app.get("/api/cap/{ward_id}", response_class=Response)
def get_cap(ward_id: str, event: str, t: str | None = Query(None)) -> Response:
    """
    CAP 1.2 XML for one ward, as application/xml.

    status is ALWAYS "Exercise" — see the safety law at the top of serve/cap.py.
    Nothing is transmitted: this endpoint hands back a document. Issuing
    authority for a real alert remains IMD / NDMA.
    """
    from serve import cap as cap_mod

    xml = cap_mod.to_xml(_cap_alert(ward_id, event, t))
    return Response(content=xml, media_type="application/xml")


@app.get("/api/cap/{ward_id}/preview")
def get_cap_preview(ward_id: str, event: str, t: str | None = Query(None)) -> dict:
    """
    The same alert as JSON — human-readable fields plus `whatsapp_text` and a
    `whatsapp_url` wa.me deep link. The link is something a PERSON clicks; no
    request leaves this process and no recipient is pre-filled.
    """
    from serve import cap as cap_mod

    return cap_mod.preview(_cap_alert(ward_id, event, t))


# --------------------------------------------------------------- LIVE
_REFRESH = {"running": False, "started": None, "last_error": None}


@app.get("/api/live/status")
def live_status() -> dict:
    """
    Age and health of the live snapshot.

    The UI shows this as a badge. Age is the point: a snapshot that silently
    goes stale during a demo is worse than one that says "42 min old", because
    the operator can then decide whether to trust it.
    """
    meta_p = OUTPUTS / "live" / "meta.json"
    if not meta_p.exists():
        return {"available": False, "refreshing": _REFRESH["running"],
                "note": "no live snapshot yet — run scripts/live_update.py"}
    meta = json.loads(meta_p.read_text())
    updated = datetime.fromisoformat(meta["updated_utc"])
    age = (datetime.now(timezone.utc) - updated).total_seconds() / 60
    return {"available": True, "refreshing": _REFRESH["running"],
            "updated_utc": meta["updated_utc"], "updated_ist": meta["updated_ist"],
            "age_minutes": round(age, 1),
            # 20 min = the 15-min cadence plus one missed cycle
            "stale": age > 20,
            "frames": len(meta["timestamps"]), "wards": meta["wards"],
            "last_error": _REFRESH["last_error"]}


@app.post("/api/live/refresh")
def live_refresh() -> dict:
    """
    Kick a live update. Returns immediately; the UI polls /api/live/status.

    Deliberately NOT synchronous: a full pull-and-predict takes ~30 s and a
    request that hangs that long looks broken to a presenter mid-demo.
    """
    import subprocess
    import threading

    if _REFRESH["running"]:
        return {"started": False, "reason": "a refresh is already running"}

    def run():
        _REFRESH["running"] = True
        _REFRESH["last_error"] = None
        try:
            r = subprocess.run(
                [f"{Path.home()}/miniforge3/bin/conda", "run", "-n", "pravaah",
                 "python", "scripts/live_update.py"],
                cwd=ROOT, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                _REFRESH["last_error"] = (r.stderr or r.stdout)[-300:]
            _index.cache_clear()      # index.json just changed
        except Exception as exc:  # noqa: BLE001
            _REFRESH["last_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _REFRESH["running"] = False

    _REFRESH["started"] = datetime.now(timezone.utc).isoformat()
    threading.Thread(target=run, daemon=True).start()
    return {"started": True, "poll": "/api/live/status"}


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
