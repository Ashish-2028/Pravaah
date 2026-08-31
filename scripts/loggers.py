#!/usr/bin/env python
"""
PRAVAAH live loggers (BUILD_PLAN A3/A14/A15/A16).

WHY THESE MATTER MORE THAN THEY LOOK
------------------------------------
Nobody serves an archive of live feeds. Our loggers ARE the archive. Every hour
they are not running is an hour of data that cannot be recovered later at any
price. That is why this is the first thing started in any session.

They serve three concrete purposes:

  1. IMD CAP alerts  -> the LEAD-TIME BENCHMARK (Proof P-3). Our threshold
     crossing vs IMD's official alert timestamp is a NUMBER, not an adjective.
     (The S3 bucket also archives back to 2019, so historical events are
     computable too — but live capture keeps the story current.)
  2. IMD radar GIFs  -> the "this is operational, not a mockup" slide, and the
     Nowcast view's radar panel.
  3. Open-Meteo + ECMWF live -> proves the pipeline runs forward, not only on
     history, and feeds a genuine "live" tab.

Everything is deduplicated by content hash and stamped in UTC.

    python scripts/loggers.py --once     # one pass of every logger, then exit
    python scripts/loggers.py            # run forever (use with caffeinate -is)
    python scripts/loggers.py --health   # freshness report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "raw" / "live"
UA = {"User-Agent": "PRAVAAH-SIH26071-research/0.1 (academic; polite polling)"}

CAP_RSS = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
# IMD public radar imagery. URLs VERIFIED by scraping mausam.imd.gov.in's own
# radar page on 31 Aug 2026 — the charter's guessed pattern
# (max_dwr_{site}.gif) 404s on every site. Real product codes:
#   sri = Surface Rainfall Intensity  <- a RAIN RATE product; the one worth
#                                        decoding for nowcasting
#   caz = Constant Altitude Z         <- reflectivity, the classic radar look
#   ppi/ppz = plan position indicator products
RADAR = {
    "delhi_sri": "https://mausam.imd.gov.in/Radar/sri_delhi.gif",
    "delhi_caz": "https://mausam.imd.gov.in/Radar/caz_delhi.gif",
    "delhi_ppz": "https://mausam.imd.gov.in/Radar/ppz_delhi.gif",
    # Chennai 404s on this naming — the site uses per-station codes we have
    # not verified, and Delhi is the pilot, so it is dropped rather than left
    # logging errors every 10 minutes.
}
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Poll intervals in seconds. Deliberately polite — these are public services
# run by a national met agency, and hammering them would be both rude and a
# fast route to an IP block.
INTERVALS = {"cap": 900, "radar": 600, "openmeteo": 3600, "ecmwf": 21600}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _seen(kind: str) -> set[str]:
    f = LOG / kind / "_hashes.txt"
    return set(f.read_text().split()) if f.exists() else set()


def _remember(kind: str, h: str) -> None:
    f = LOG / kind / "_hashes.txt"
    with f.open("a") as fh:
        fh.write(h + "\n")


# ------------------------------------------------------------------ loggers
def log_cap() -> str:
    d = LOG / "cap"
    d.mkdir(parents=True, exist_ok=True)
    r = requests.get(CAP_RSS, headers=UA, timeout=60)
    r.raise_for_status()
    h = _sha(r.content)
    if h in _seen("cap"):
        return "cap: unchanged"
    (d / f"cap_{_now()}_{h}.xml").write_bytes(r.content)
    _remember("cap", h)
    n = r.text.count("<item>")
    return f"cap: NEW ({n} items, {len(r.content)//1024} KB)"


def log_radar() -> str:
    d = LOG / "radar"
    d.mkdir(parents=True, exist_ok=True)
    seen = _seen("radar")
    out = []
    for name, url in RADAR.items():
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code != 200 or not r.content:
                out.append(f"{name}:HTTP{r.status_code}")
                continue
            h = _sha(r.content)
            if h in seen:
                out.append(f"{name}:same")
                continue
            # VALIDATE BEFORE ARCHIVING. A truncated response still has a
            # stable sha, so without this check a corrupt capture gets stored
            # AND remembered — poisoning the archive permanently and breaking
            # the publish step later. Verify it decodes as an image first.
            try:
                from io import BytesIO
                from PIL import Image
                # .load(), NOT .verify(). verify() only checks headers and
                # happily passes a GIF whose pixel data is truncated — which is
                # exactly the failure we hit. load() actually decodes.
                Image.open(BytesIO(r.content)).load()
            except Exception:  # noqa: BLE001
                out.append(f"{name}:corrupt")
                continue
            (d / f"{name}_{_now()}_{h}.gif").write_bytes(r.content)
            _remember("radar", h)
            out.append(f"{name}:NEW")
        except requests.RequestException as e:
            out.append(f"{name}:{type(e).__name__}")
    return "radar: " + " ".join(out)


def log_openmeteo() -> str:
    """Live 0-72 h multi-model forecast on the NCR lattice centre."""
    d = LOG / "openmeteo"
    d.mkdir(parents=True, exist_ok=True)
    params = {
        "latitude": 28.65, "longitude": 77.22,
        "hourly": "precipitation,temperature_2m,relative_humidity_2m,cape",
        "models": "ecmwf_ifs025,gfs_seamless,icon_seamless",
        "forecast_days": 3, "timezone": "UTC",
    }
    r = requests.get(OM_FORECAST, params=params, headers=UA, timeout=90)
    r.raise_for_status()
    payload = r.json()
    # issue_time = fetch time. This is the honest stamp for a live pull: it is
    # the moment the data became available to US (charter R4).
    payload["_pravaah_issue_time"] = datetime.now(timezone.utc).isoformat()
    (d / f"om_{_now()}.json").write_text(json.dumps(payload))
    return "openmeteo: ok"


def log_ecmwf() -> str:
    """ECMWF open-data IFS run over the NCR box."""
    d = LOG / "ecmwf"
    d.mkdir(parents=True, exist_ok=True)
    try:
        from ecmwf.opendata import Client
    except ImportError:
        return "ecmwf: package missing"
    try:
        c = Client(source="ecmwf")
        target = d / f"ifs_{_now()}.grib2"
        c.retrieve(type="fc", param=["tp", "2t"], step=[6, 12, 24],
                   target=str(target))
        return f"ecmwf: ok ({target.stat().st_size//1024} KB)"
    except Exception as e:  # noqa: BLE001
        return f"ecmwf: {type(e).__name__}"


LOGGERS = {"cap": log_cap, "radar": log_radar,
           "openmeteo": log_openmeteo, "ecmwf": log_ecmwf}


def health() -> int:
    print(f"PRAVAAH logger health  {_now()}")
    ok = True
    for kind in LOGGERS:
        d = LOG / kind
        files = sorted(d.glob("*")) if d.exists() else []
        files = [f for f in files if not f.name.startswith("_")]
        if not files:
            print(f"  {kind:<10} NO FILES")
            ok = False
            continue
        newest = max(files, key=lambda f: f.stat().st_mtime)
        age_min = (time.time() - newest.stat().st_mtime) / 60
        warn = age_min > INTERVALS[kind] / 60 * 3
        print(f"  {kind:<10} {len(files):>5} files   newest {age_min:6.1f} min ago"
              f"   {'WARN' if warn else 'ok'}")
        ok = ok and not warn
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--health", action="store_true")
    args = ap.parse_args()

    LOG.mkdir(parents=True, exist_ok=True)
    if args.health:
        return health()

    last: dict[str, float] = {k: 0.0 for k in LOGGERS}
    while True:
        now = time.time()
        for kind, fn in LOGGERS.items():
            if args.once or now - last[kind] >= INTERVALS[kind]:
                try:
                    print(f"[{_now()}] {fn()}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[{_now()}] {kind}: FAILED {type(e).__name__}: {e}",
                          flush=True)
                last[kind] = now
        if args.once:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
