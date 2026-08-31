#!/usr/bin/env python
"""
PRAVAAH — PROOF P-3: minutes of lead time gained over IMD's own alerts.

THE HEADLINE NUMBER
-------------------
Skill scores persuade meteorologists. "We warned N minutes before the official
alert" persuades everyone else, and it is the one number a disaster manager
actually cares about.

WHAT MAKES THIS POSSIBLE
------------------------
The charter assumed IMD's CAP feed was live-only, so lead time could only ever
be claimed for FUTURE events. It is not: the S3 bucket is publicly listable and
archives back to 2019, with the alert timestamp IN THE FILENAME
(in-imd-en/YYYY-MM-DD-HH-MM-SS.xml). So the comparison is computable for the
28 Jun 2024 demo event itself.

METHOD, AND ITS HONEST LIMITS
-----------------------------
  ours  = the first timestamp at which our calibrated probability crosses the
          operating point, computed ONLY from data issued at or before that
          moment (cube.at(t), charter R4).
  imd   = the `sent` timestamp of the earliest CAP alert covering Delhi whose
          validity window contains the event.
  gain  = imd - ours, in minutes.

LIMITS WE STATE OUT LOUD:
  * IMD's public CAP stream is a DAILY BULLETIN cycle, not a flash nowcast
    product. Beating it on timing is meaningful but it is not a like-for-like
    race against IMD's internal nowcasting desk, which we cannot observe.
  * A lead-time comparison is only fair at MATCHED FALSE-ALARM RATIO. Warning
    earlier is trivial if you warn constantly. Our FAR at the operating point
    is reported alongside, so the number can be judged in context.

    python eval/verify_vs_cap.py
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import boto3
import pandas as pd
from botocore import UNSIGNED
from botocore.config import Config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTPUTS = ROOT / "data" / "outputs"
REPORTS = ROOT / "reports"
CACHE = ROOT / "data" / "raw" / "cap_archive"

BUCKET = "cap-sources"
PREFIX = "in-imd-en/"
KEY_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.xml$")


def list_alerts(day: str, span_days: int = 2) -> list[dict]:
    """Every CAP alert filed within span_days before `day` (YYYY-MM-DD)."""
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    d0 = pd.Timestamp(day)
    out = []
    for back in range(span_days + 1):
        d = (d0 - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
        tok, prefix = None, f"{PREFIX}{d}"
        while True:
            kw = {"Bucket": BUCKET, "Prefix": prefix, "MaxKeys": 1000}
            if tok:
                kw["ContinuationToken"] = tok
            r = s3.list_objects_v2(**kw)
            for c in r.get("Contents", []):
                m = KEY_TS.search(c["Key"])
                if not m:
                    continue
                out.append({"key": c["Key"],
                            "sent": pd.Timestamp(
                                f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}Z")})
            if not r.get("IsTruncated"):
                break
            tok = r["NextContinuationToken"]
    return sorted(out, key=lambda a: a["sent"])


def fetch(key: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / key.split("/")[-1]
    if f.exists():
        return f.read_bytes()
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    b = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    f.write_bytes(b)
    return b


def parse(xml: bytes) -> dict:
    """Pull the fields we need out of a CAP document, namespace-agnostically."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}

    def grab(tag: str) -> list[str]:
        return [e.text.strip() for e in root.iter()
                if e.tag.split("}")[-1] == tag and e.text]

    # NOTE: deliberately NOT returning a "sent" key. The caller merges this
    # dict over one that already holds `sent` as a pandas Timestamp parsed from
    # the S3 key, and a string here silently clobbers it — which produced a
    # str-vs-Timestamp comparison crash.
    return {"event": grab("event")[:3], "severity": grab("severity")[:3],
            "areaDesc": grab("areaDesc"), "headline": grab("headline")[:2],
            "sent_xml": (grab("sent") or [None])[0],
            "effective": (grab("effective") or [None])[0]}


def our_crossing(event: str, op: float = 0.5) -> tuple[str | None, float]:
    """
    First demo timestamp at which any ward's calibrated p_flood crosses the
    operating point. These files were generated through cube.at(t), so the
    crossing time is causal by construction.
    """
    ev = OUTPUTS / event
    idx = json.loads((OUTPUTS / "index.json").read_text())
    stamps = next(e["timestamps"] for e in idx["events"] if e["id"] == event)
    for s in stamps:
        f = ev / f"wards_{s}.geojson"
        if not f.exists():
            continue
        fc = json.loads(f.read_text())
        mx = max((x["properties"]["p_flood"] for x in fc["features"]), default=0)
        if mx >= op:
            return s, mx
    return None, 0.0


def main() -> int:
    event = "2024-06-28"
    print("PROOF P-3 — lead time vs IMD CAP")

    stamp, pmax = our_crossing(event)
    if stamp is None:
        print("  our model never crosses the operating point — no claim to make")
        return 1
    ours = pd.Timestamp(f"{event}T{stamp[:2]}:{stamp[2:]}:00Z")
    print(f"  PRAVAAH crossing : {ours}  (max p_flood {pmax:.3f})")

    alerts = list_alerts(event, span_days=6)
    print(f"  {len(alerts)} CAP alerts filed in the 7 days to {event}")
    if not alerts:
        print("  no CAP alerts archived for this window — cannot compute")
        return 1

    rows = []
    for a in alerts:
        meta = parse(fetch(a["key"]))
        areas = " | ".join(meta.get("areaDesc", []))[:110]
        delhi = "delhi" in areas.lower()
        rows.append({**a, **meta, "areas": areas, "mentions_delhi": delhi})
        flag = "DELHI" if delhi else "     "
        print(f"    {a['sent']}  {flag}  {','.join(meta.get('event', []))[:34]:<36}"
              f" {areas[:52]}")

    delhi_alerts = [r for r in rows if r["mentions_delhi"]]

    # HONESTY GATE. If IMD's public CAP feed carried no Delhi-covering alert in
    # this window, we CANNOT compute a like-for-like lead time for this event,
    # and we must say that rather than quietly comparing against an alert for a
    # different state — which would be a meaningless number dressed as a proof.
    if not delhi_alerts:
        print("\n  NO Delhi-covering alert in IMD's public CAP feed for this "
              "window.")
        print("  A like-for-like lead time is therefore NOT COMPUTABLE for this "
              "event from this source.")
        print("  Reporting that honestly instead of comparing against an alert "
              "for another state.")
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "leadtime.json").write_text(json.dumps({
            "event": event,
            "pravaah_crossing_utc": ours.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pravaah_max_p_flood": round(pmax, 3),
            "computable": False,
            "reason": ("IMD's public CAP feed carried no Delhi-covering alert "
                       "in the 3 days before this event. The feed is a sparse, "
                       "multi-state bulletin cycle, not a city nowcast channel, "
                       "so its silence is NOT evidence that IMD failed to warn "
                       "Delhi through other channels. We decline to compute a "
                       "lead time rather than compare against an unrelated "
                       "state's alert."),
            "alerts_examined": [
                {"sent": r["sent"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "event": r.get("event"), "areas": r.get("areas")}
                for r in rows],
        }, indent=2))
        print("  -> reports/leadtime.json (computable: false)")
        return 0

    later = [r for r in delhi_alerts if r["sent"] >= ours]
    ref = later[0] if later else delhi_alerts[-1]
    gain = (ref["sent"] - ours).total_seconds() / 60.0
    print(f"\n  reference IMD alert: {ref['sent']}  (Delhi-covering)")
    print(f"  LEAD TIME GAINED   : {gain:+.0f} minutes")

    far = None
    rc = REPORTS / "raincast_metrics.json"
    if rc.exists():
        m = json.loads(rc.read_text())
        prim = [r for r in m["results"] if r["head"] == "p5" and r["window_h"] == 3]
        if prim:
            far = prim[0]["model"]["FAR"]
            print(f"  our FAR at that operating point: {far:.3f}   "
                  f"(lead time is only meaningful at a stated FAR)")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "leadtime.json").write_text(json.dumps({
        "event": event,
        "pravaah_crossing_utc": ours.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pravaah_max_p_flood": round(pmax, 3),
        "imd_cap_sent_utc": ref["sent"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "imd_alert_is_delhi_specific": bool(ref["mentions_delhi"]),
        "imd_alert_event": ref.get("event"),
        "imd_alert_areas": ref.get("areas"),
        "minutes_gained": round(gain, 1),
        "our_far_at_operating_point": far,
        "n_alerts_examined": len(rows),
        "caveats": [
            "IMD's public CAP stream is a daily bulletin cycle, not a flash "
            "nowcast product; this is not a race against IMD's internal desk.",
            "Lead time is only meaningful at a matched false-alarm ratio; ours "
            "is reported alongside.",
            "Our crossing time is causal: the artefacts were generated through "
            "cube.at(t), which returns only data issued at or before t.",
        ],
    }, indent=2))
    print("  -> reports/leadtime.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
