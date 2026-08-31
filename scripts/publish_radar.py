#!/usr/bin/env python
"""
PRAVAAH — publish logged IMD radar imagery as demo frames (A14).

WHAT THIS IS AND IS NOT
-----------------------
IS:  the actual IMD Delhi DWR imagery our logger has been capturing every 10
     minutes, republished as PNGs the UI can animate. It is the "this is
     operational right now, not a mockup" evidence — slide 3 of the deck.

IS NOT: a decoded radar product. We are showing IMD's rendered GIF, not
     reflectivity values extracted from it. v0 DISPLAYS radar; DECODING is the
     radar-era plan, and the difference must be stated plainly rather than
     letting a radar-looking panel imply we ingested radar data. Nothing in any
     model consumes these pixels.

Product codes (verified from mausam.imd.gov.in's own radar page):
    sri = Surface Rainfall Intensity   caz = Constant Altitude Z   ppz = PPI Z

    python scripts/publish_radar.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "live" / "radar"
OUT = ROOT / "data" / "outputs" / "live" / "frames"

STAMP = re.compile(r"^(?P<prod>[a-z_]+)_(?P<ts>\d{8}T\d{6}Z)_")
KEEP_PER_PRODUCT = 24          # ~4 hours at a 10-minute cadence

PRODUCT_LABEL = {
    "delhi_sri": "Surface Rainfall Intensity",
    "delhi_caz": "Constant Altitude Reflectivity",
    "delhi_ppz": "PPI Reflectivity",
}


def main() -> int:
    if not SRC.exists():
        print("no radar captures yet — is scripts/loggers.py running?")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
        have_pil = True
    except ImportError:
        have_pil = False
        print("  Pillow unavailable — copying GIFs unconverted")

    by_product: dict[str, list[Path]] = {}
    for f in sorted(SRC.glob("*.gif")):
        m = STAMP.match(f.name)
        if m:
            by_product.setdefault(m["prod"], []).append(f)

    manifest = {}
    for prod, files in by_product.items():
        files = sorted(files, key=lambda p: STAMP.match(p.name)["ts"])[-KEEP_PER_PRODUCT:]
        frames = []
        for f in files:
            ts = STAMP.match(f.name)["ts"]
            if have_pil:
                dst = OUT / f"{prod}_{ts}.png"
                if not dst.exists():
                    try:
                        Image.open(f).convert("RGB").save(dst, "PNG", optimize=True)
                    except OSError as exc:
                        # A truncated capture (interrupted download) must not
                        # abort the whole batch. Skip it and say so — a missing
                        # frame is fine, a crashed publish step before a demo
                        # is not.
                        print(f"    SKIP corrupt {f.name}: {exc}")
                        dst.unlink(missing_ok=True)
                        continue
            else:
                dst = OUT / f"{prod}_{ts}.gif"
                if not dst.exists():
                    shutil.copyfile(f, dst)
            iso = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc).isoformat()
            frames.append({"url": f"/static/live/frames/{dst.name}",
                           "captured_utc": iso, "stamp": ts})
        if not frames:
            print(f"  {prod:<12} no usable frames — skipped")
            continue
        manifest[prod] = {
            "label": PRODUCT_LABEL.get(prod, prod),
            "site": "Delhi DWR (IMD public imagery)",
            "frames": frames,
            "n": len(frames),
        }
        print(f"  {prod:<12} {len(frames):>3} frames  "
              f"{frames[0]['stamp']} .. {frames[-1]['stamp']}")

    (OUT / "manifest.json").write_text(json.dumps({
        "products": manifest,
        "generated": datetime.now(timezone.utc).isoformat(),
        "disclaimer": ("IMD public radar imagery, captured live by our logger "
                       "every 10 minutes and displayed as-is. NOT decoded — no "
                       "model consumes these pixels. Decoding raw DWR volumes "
                       "is the radar-era roadmap item."),
    }, indent=2))

    total = sum(v["n"] for v in manifest.values())
    print(f"\n  {total} frames across {len(manifest)} products -> "
          f"{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
