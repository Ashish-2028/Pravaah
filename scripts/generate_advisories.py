#!/usr/bin/env python
"""
PRAVAAH — pre-generate and cache every advisory (BUILD_PLAN P12-T2).

The demo serves cache. This writes it. Runs offline: with no API key the
deterministic renderer produces every advisory, so the cache is complete
regardless of network or credentials.

    python scripts/generate_advisories.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from serve.advisory import generate  # noqa: E402

OUTPUTS = ROOT / "data" / "outputs"
TOP_N = 12          # advisories for the N riskiest wards per frame


def main() -> int:
    idx = json.loads((OUTPUTS / "index.json").read_text())
    total = 0
    for ev in idx["events"]:
        ev_id = ev["id"]
        ctx = ev["name"]
        for stamp in ev["timestamps"]:
            f = OUTPUTS / ev_id / f"wards_{stamp}.geojson"
            if not f.exists():
                continue
            fc = json.loads(f.read_text())
            ranked = sorted(fc["features"],
                            key=lambda x: -x["properties"]["risk_score"])[:TOP_N]
            for feat in ranked:
                p = feat["properties"]
                out = OUTPUTS / ev_id / f"advisory_{p['ward_id']}_{stamp}.json"
                adv = generate(p, ctx)
                adv["cached"] = True
                out.write_text(json.dumps(adv, ensure_ascii=False, indent=1))
                total += 1
            print(f"  {ev_id} {stamp}: {len(ranked)} advisories", flush=True)
    print(f"\n  {total} advisories cached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
