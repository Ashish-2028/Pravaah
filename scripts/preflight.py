#!/usr/bin/env python
"""
PRAVAAH — the pre-demo gate. Run this before presenting.

Every check here exists because the corresponding failure ACTUALLY HAPPENED
during the build, not because it seemed like a good idea:

  leakage        the suite once passed VACUOUSLY (issue_time == valid_time on
                 every row, so the accessor filtered nothing)
  artefacts      the demo window moved and 31 stale files from the old window
                 stayed on disk beside the current ones
  consistency    advisories from a superseded model run quoted probabilities
                 that no longer matched the map next to them
  offline        the Streamlit fallback shipped with OpenStreetMap tiles, which
                 would have rendered as grey squares with wifi off
  freshness      loggers die silently; every hour lost is unrecoverable

    python scripts/preflight.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "data" / "outputs"
CONDA = f"{Path.home()}/miniforge3/bin/conda"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def leakage() -> None:
    r = subprocess.run([CONDA, "run", "-n", "pravaah", "--no-capture-output",
                        "python", "eval/leakage_tests.py"],
                       cwd=ROOT, capture_output=True, text=True)
    passed = "ALL 6 LEAKAGE TESTS PASS" in r.stdout
    n = r.stdout.count("[PASS]")
    check("no-look-ahead suite", passed, f"{n}/6 sub-tests")


def artefacts() -> None:
    idx = json.loads((OUTPUTS / "index.json").read_text())
    pat = re.compile(r"_(\d{4})\.(?:geojson|json)$")
    stale = []
    for ev in idx["events"]:
        d = OUTPUTS / ev["id"]
        valid = set(ev["timestamps"])
        for f in d.iterdir() if d.is_dir() else []:
            m = pat.search(f.name)
            if m and m[1] not in valid:
                stale.append(f.name)
        missing = [s for s in ev["timestamps"]
                   if not (d / f"wards_{s}.geojson").exists()]
        check(f"artefacts complete ({ev['id']})", not missing,
              f"{len(ev['timestamps'])} frames"
              + (f", MISSING {missing}" if missing else ""))
    check("no stale artefacts", not stale,
          f"{len(stale)} stale" if stale else "index and disk agree")


def consistency() -> None:
    bad = checked = 0
    for f in sorted(OUTPUTS.glob("*/advisory_*.json")):
        m = re.search(r"advisory_(.+)_(\d{4})\.json$", f.name)
        if not m:
            continue
        adv = json.loads(f.read_text())
        wf = f.parent / f"wards_{m[2]}.geojson"
        if not wf.exists():
            bad += 1
            continue
        fc = json.loads(wf.read_text())
        p = next((x["properties"] for x in fc["features"]
                  if x["properties"]["ward_id"] == m[1]), None)
        if p is None or f"{round(p['p_flood'] * 100)}%" not in adv.get("advisory_en", ""):
            bad += 1
        checked += 1
    check("advisories match the map", bad == 0,
          f"{checked} checked, {bad} inconsistent")


def offline() -> None:
    """No artefact the demo serves may reference an external host."""
    bad = []
    scan = [ROOT / "ui" / "dist", OUTPUTS, ROOT / "ui-fallback"]
    allow = re.compile(r"localhost|127\.0\.0\.1|w3\.org|schema\.org|"
                       r"github\.com|maplibre\.org|react\.dev|reactrouter|"
                       r"redux|openstreetmap\.org/wiki|bit\.ly|tailwindcss\.com")
    url = re.compile(rb"https?://[A-Za-z0-9./_-]+")
    for base in scan:
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix in {".png", ".gif", ".parquet", ".nc"}:
                continue
            try:
                blob = f.read_bytes()
            except OSError:
                continue
            for u in set(url.findall(blob)):
                s = u.decode("utf8", "ignore")
                if not allow.search(s):
                    bad.append(f"{f.relative_to(ROOT)}: {s[:60]}")
    check("no external hosts in served files", not bad,
          f"{len(bad)} reference(s)" if bad else "airplane-safe")
    for b in bad[:5]:
        print(f"        {b}")


def freshness() -> None:
    live = ROOT / "data" / "raw" / "live"
    if not live.exists():
        check("loggers capturing", False, "no live/ directory")
        return
    # Budgets are now on POLL age (3x the interval), not content age.
    for kind, budget_min in (("cap", 45), ("radar", 30),
                             ("openmeteo", 180), ("ecmwf", 800)):
        d = live / kind
        files = [f for f in d.glob("*") if not f.name.startswith("_")] if d.exists() else []
        if not files:
            check(f"logger {kind}", False, "no captures")
            continue
        # Liveness = did a POLL succeed recently, not did content change.
        # These loggers dedupe by hash, so a healthy logger on an unchanged
        # feed writes nothing; judging by file mtime failed a working CAP
        # logger because IMD publishes roughly daily.
        content_age = (time.time() - max(f.stat().st_mtime for f in files)) / 60
        hb = d / "_lastpoll"
        poll_age = ((time.time() - hb.stat().st_mtime) / 60
                    if hb.exists() else content_age)
        check(f"logger {kind}", poll_age < budget_min,
              f"{len(files)} files, polled {poll_age:.0f} min ago, "
              f"newest content {content_age:.0f} min ago")


def proofs() -> None:
    m = ROOT / "reports" / "metrics.json"
    if not m.exists():
        check("metrics.json present", False, "missing")
        return
    d = json.loads(m.read_text())
    check("ablation populated", len(d.get("ablation", [])) >= 5,
          f"{len(d.get('ablation', []))} rows")
    check("reliability populated", len(d.get("reliability", {})) >= 1,
          f"{len(d.get('reliability', {}))} heads")
    check("stated limits present", len(d.get("stated_limits", [])) >= 3,
          f"{len(d.get('stated_limits', []))} limits")
    fake = json.dumps(d).lower().count("[fake]")
    check("no placeholder values left", fake == 0,
          f"{fake} '[FAKE]' strings" if fake else "all real")


def main() -> int:
    print("=" * 70)
    print("PRAVAAH pre-demo preflight")
    print("=" * 70)
    for section, fn in (("LEAKAGE", leakage), ("ARTEFACTS", artefacts),
                        ("CONSISTENCY", consistency), ("OFFLINE", offline),
                        ("LOGGERS", freshness), ("PROOFS", proofs)):
        print(f"\n{section}")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{section.lower()} checks ran", False,
                  f"{type(exc).__name__}: {exc}")

    print("\n" + "=" * 70)
    failed = [n for n, ok, _ in RESULTS if not ok]
    if failed:
        print(f"{len(failed)} of {len(RESULTS)} CHECKS FAILED — do not present yet")
        for n in failed:
            print(f"  - {n}")
        return 1
    print(f"ALL {len(RESULTS)} CHECKS PASS — clear to present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
