#!/usr/bin/env python
"""
PRAVAAH — remove artefacts not declared in index.json.

WHY THIS MATTERS. The demo window moved once already (0400-0930Z, which was the
wrong hours, to 0000-0700Z). Frames from the old window stayed on disk, so
data/outputs/ held 17 ward files while index.json declared 15. The backend
resolves timestamps from the index so nothing broke — but a stale artefact from
a superseded model run sitting beside current ones is exactly the kind of thing
that silently serves wrong numbers after the next window change. Reconcile
explicitly.

    python scripts/reconcile_outputs.py --dry-run
    python scripts/reconcile_outputs.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "data" / "outputs"
PAT = re.compile(r"_(\d{4})\.(?:geojson|json)$")


def main() -> int:
    dry = "--dry-run" in sys.argv
    idx = json.loads((OUTPUTS / "index.json").read_text())
    removed = kept = 0
    for ev in idx["events"]:
        d = OUTPUTS / ev["id"]
        if not d.is_dir():
            continue
        valid = set(ev["timestamps"])
        print(f"  {ev['id']}: index declares {len(valid)} timestamps")
        for f in sorted(d.iterdir()):
            if f.is_dir() or f.name == "index.json":
                continue
            m = PAT.search(f.name)
            if not m:
                continue
            if m[1] in valid:
                kept += 1
            else:
                print(f"    stale {f.name}")
                if not dry:
                    f.unlink()
                removed += 1
    print(f"\n  {kept} current, {removed} stale{' (dry run)' if dry else ' removed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
