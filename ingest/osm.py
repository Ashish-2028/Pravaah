#!/usr/bin/env python
"""
PRAVAAH A9 / P2-T6 — OpenStreetMap pull via osmnx (Overpass).

Fetches, for the AOI bbox in configs/aoi_delhi_ncr.yaml:
    * waterways        waterway = drain | canal | river   (the drainage network)
    * hospitals        amenity  = hospital / clinic
    * schools          amenity  = school / college / university
    * pumps            man_made = pumping_station | water_works, amenity=pumping_station
    * drive network    ox.graph_from_bbox(..., network_type="drive")

Charter rules honoured
----------------------
R6  EVERYTHING IS CACHED. Overpass rate-limits hard and this is a 20-hour
    build. Two layers of caching:
      1. osmnx's own response cache -> data/raw/osm_cache/  (raw JSON)
      2. parsed GeoParquet          -> data/raw/osm/*.parquet
    A re-run with both present makes ZERO network calls. --force to refresh.
R7  bbox comes from the YAML; no coordinate is written in this file.
R3  Prints feature counts and geometry-type breakdowns per layer.

Robustness
----------
Overpass times out on big-bbox queries at peak. Each layer is tried whole
first; on failure it retries with exponential backoff, and then falls back to
splitting the bbox into quadrants and unioning the results.

Usage
-----
    python ingest/osm.py                 # all layers (cached)
    python ingest/osm.py --force         # ignore parquet cache, re-query
    python ingest/osm.py --status        # what is on disk
"""
from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
RAW = ROOT / "data" / "raw" / "osm"
CACHE = ROOT / "data" / "raw" / "osm_cache"
CACHE_DIRECT = ROOT / "data" / "raw" / "osm_cache_direct"

# Tag queries. These are OSM schema, not region facts — they are the same for
# any city on Earth, which is exactly why they live in code and the bbox does not.
LAYERS: dict[str, dict] = {
    "waterways": {"waterway": ["drain", "canal", "river", "stream", "ditch"]},
    "hospitals": {"amenity": ["hospital", "clinic"]},
    "schools": {"amenity": ["school", "college", "university"]},
    "pumps": {
        "man_made": ["pumping_station", "water_works", "water_tower"],
        "amenity": ["pumping_station"],
    },
    # The drivable road network as plain WAYS.
    #
    # Deliberately NOT ox.graph_from_bbox. Probed 31 Aug 2026: the graph query
    # over the full 80x73 km AOI hung for 35+ minutes while Overpass's own
    # /api/status reported no query running for us — the graph builder is by
    # far the heaviest thing osmnx can ask for, and it is the one request the
    # server drops. The feature query below returns the same geometry in
    # seconds. P2-T11 needs road KILOMETRES per ward, which is a length sum
    # over LineStrings; it does not need a routable topology. If a later phase
    # needs routing, pull the graph then, separately, and cache it.
    "roads": {"highway": [
        "motorway", "motorway_link", "trunk", "trunk_link",
        "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "unclassified", "residential",
        "living_street",
    ]},
}

# Columns worth keeping. Everything else in OSM is free-form and will not
# survive a parquet round-trip.
KEEP = ["osmid", "name", "amenity", "waterway", "man_made", "highway", "width",
        "intermittent", "tunnel", "covered", "geometry"]


def load_cfg() -> dict:
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


def setup_osmnx():
    import socket

    import osmnx as ox

    # A hard socket-level deadline. ox.settings.requests_timeout is the
    # Overpass *server-side* [timeout:] directive, not an HTTP socket timeout,
    # so a connection the server accepts and then abandons blocks the client
    # forever (observed twice: 35 min with zero server-side activity). This
    # turns that hang into an ordinary exception the retry loop can act on.
    socket.setdefaulttimeout(SOCKET_TIMEOUT_S)

    CACHE.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE)
    ox.settings.requests_timeout = 300
    ox.settings.log_console = False
    # osmnx's built-in rate limiter polls /api/status and SLEEPS until it
    # believes a slot is free. Observed 31 Aug 2026: it parked indefinitely
    # while /api/status reported "2 slots available now" and a hand-rolled
    # curl query to the same endpoint returned in 1.1 s. We make a handful of
    # requests, tiled and backed off by this module already, so its own
    # retry/backoff is the one to trust.
    ox.settings.overpass_rate_limit = False
    return ox


def _sanitize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep a stable, parquet-safe column set."""
    gdf = gdf.reset_index()
    cols = [c for c in KEEP if c in gdf.columns]
    if "geometry" not in cols:
        cols.append("geometry")
    out = gdf[cols].copy()
    for c in out.columns:
        if c == "geometry":
            continue
        out[c] = out[c].astype(str).where(out[c].notna(), None)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs)


def _tiles(bbox: dict, n: int = 2) -> list[tuple[float, float, float, float]]:
    """Split the AOI into an n x n lattice of sub-bboxes."""
    xs = np.linspace(bbox["west"], bbox["east"], n + 1)
    ys = np.linspace(bbox["south"], bbox["north"], n + 1)
    return [(xs[i], ys[j], xs[i + 1], ys[j + 1])
            for j in range(n) for i in range(n)]


def _quadrants(bbox: dict) -> list[tuple[float, float, float, float]]:
    return _tiles(bbox, 2)


# Layers too heavy for one whole-AOI Overpass call. Probed 31 Aug 2026: the
# whole-AOI `highway` query hangs indefinitely — the client blocks while
# overpass-api.de's own /api/status reports NO query running for us, so it
# never raises and never trips a retry. Tiling turns one request the server
# silently drops into N it actually answers. Values are the lattice size n
# (n x n tiles).
TILE_FIRST = {"roads": 4}

# Hard wall-clock ceiling on any single socket operation. See setup_osmnx().
SOCKET_TIMEOUT_S = 180.0

# Layers fetched by _overpass_direct() instead of osmnx. See that function.
DIRECT_LAYERS = {"roads"}
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
USER_AGENT = "PRAVAAH-SIH2026 (static hydrology ingest; contact via repo)"


def _overpass_direct(tags: dict, tile: tuple, timeout: int = 180
                     ) -> gpd.GeoDataFrame:
    """Query Overpass with plain `requests`, bypassing osmnx's HTTP stack.

    WHY THIS EXISTS (probed 31 Aug 2026). osmnx's requests could not reach
    overpass-api.de at all for the road layer — ConnectionError / "Connection
    refused" on every attempt — while, at the same moment:
      * `curl` to /api/interpreter returned HTTP 200 in 1.1 s, and
      * plain `requests.post` from the SAME interpreter returned 200 in 0.9 s
        against overpass-api.de, overpass.osm.ch and maps.mail.ru.
    This environment ships urllib3-future (note `urllib3/contrib/resolver/` in
    the tracebacks), whose custom DNS resolver and HTTP/2 negotiation osmnx's
    session picks up. Rather than fight a transport bug in a 20-hour build,
    the heavy layer takes the path that demonstrably works.

    Raw responses are cached to data/raw/osm_cache_direct/ (charter R6).
    """
    import json
    import hashlib

    import requests
    from shapely.geometry import LineString

    (w, s, e, n) = tile
    key, vals = next(iter(tags.items()))
    pattern = "|".join(vals)
    q = (f'[out:json][timeout:{timeout}];'
         f'way["{key}"~"^({pattern})$"]({s},{w},{n},{e});out geom;')

    CACHE_DIRECT.mkdir(parents=True, exist_ok=True)
    cf = CACHE_DIRECT / (hashlib.sha1(q.encode()).hexdigest() + ".json")
    if cf.exists():
        data = json.loads(cf.read_text())
    else:
        last = None
        for attempt, url in enumerate(OVERPASS_ENDPOINTS * 2):
            try:
                r = requests.post(url, data={"data": q}, timeout=timeout + 30,
                                  headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                data = r.json()
                # Overpass signals timeouts and out-of-memory in a `remark`
                # field WITH HTTP 200 and an empty element list. Caching that
                # would silently bake a hole into the layer.
                if data.get("remark"):
                    raise RuntimeError(f"Overpass remark: {data['remark'][:120]}")
                # NEVER cache an empty result. Overpass under load returns
                # HTTP 200 with zero elements and no remark; caching that
                # bakes a permanent hole into the layer that a re-run would
                # happily "resume" past. An empty tile is treated as a
                # failure and retried; a genuinely empty tile costs us only
                # the retries.
                if not data.get("elements"):
                    raise RuntimeError("empty element list (Overpass under "
                                       "load) — not cached, will retry")
                cf.write_text(json.dumps(data))
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                print(f"        {url.split('/')[2]}: "
                      f"{type(exc).__name__}: {str(exc)[:80]}", flush=True)
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"all Overpass endpoints failed: {last}")

    rows = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        pts = [(p["lon"], p["lat"]) for p in el["geometry"]]
        if len(pts) < 2:
            continue
        t = el.get("tags", {})
        rows.append({"osmid": el["id"], key: t.get(key),
                     "name": t.get("name"), "geometry": LineString(pts)})
    if not rows:
        return gpd.GeoDataFrame({"osmid": [], key: [], "name": [],
                                 "geometry": []},
                                geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _fetch_tile_adaptive(tags: dict, tile: tuple, label: str,
                         depth: int = 0, max_depth: int = 2) -> list | None:
    """Fetch one tile, splitting it into quarters if Overpass cannot serve it.

    Dense central-Delhi tiles blow Overpass's time/memory limits and come back
    as HTTP 200 with an empty element list. The fix is not to retry the same
    query harder, it is to ask a smaller question — so a failure recurses into
    2x2 sub-tiles. Returns None only if even the smallest sub-tile fails.
    """
    try:
        g = _overpass_direct(tags, tile)
        print(f"      tile {label}: {len(g)} ways", flush=True)
        return [g] if len(g) else []
    except Exception as exc:  # noqa: BLE001
        if depth >= max_depth:
            print(f"      tile {label}: FAILED at max depth — "
                  f"{str(exc)[:80]}", flush=True)
            return None
        print(f"      tile {label}: {str(exc)[:70]} -> splitting 2x2",
              flush=True)
        w, s, e, n_ = tile
        sub = _tiles({"west": w, "south": s, "east": e, "north": n_}, 2)
        out, failed = [], 0
        for k, q in enumerate(sub, 1):
            r = _fetch_tile_adaptive(tags, q, f"{label}.{k}", depth + 1,
                                     max_depth)
            if r is None:
                failed += 1
            else:
                out.extend(r)
        return None if failed == len(sub) else out


def _write_manifest(name: str, total: int, missing: list) -> None:
    """Record layer completeness next to the parquet.

    A road layer with a hole in central Delhi is WORSE than no road layer:
    the numbers look plausible and nothing complains. This file is how
    downstream code finds out."""
    import json

    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{name}.meta.json").write_text(json.dumps(dict(
        layer=name, tiles_total=total, tiles_missing=missing,
        complete=not missing,
        fetched=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), indent=2))


def _tiled_fetch(ox, name: str, tags: dict, bbox: dict, n: int,
                 retries: int = 3) -> list:
    if name in DIRECT_LAYERS:
        parts, missing = [], []
        tiles = _tiles(bbox, n)
        for i, q in enumerate(tiles, 1):
            got = _fetch_tile_adaptive(tags, q, f"{i}/{len(tiles)}")
            if got is None:
                missing.append(i)
                continue
            parts.extend(got)
        _write_manifest(name, len(tiles), missing)
        if missing:
            print(f"    !! {len(missing)}/{len(tiles)} tiles MISSING "
                  f"({missing}). The layer is INCOMPLETE and "
                  f"{name}.meta.json says so — downstream code must refuse to "
                  f"treat it as complete. Re-run to retry only these tiles.")
        return parts

    parts = []
    tiles = _tiles(bbox, n)
    for i, q in enumerate(tiles, 1):
        for attempt in range(retries):
            try:
                g = ox.features_from_bbox(q, tags)
                print(f"      tile {i}/{len(tiles)}: {len(g)} features",
                      flush=True)
                parts.append(g)
                break
            except Exception as exc:  # noqa: BLE001
                # An EmptyOverpassResponse for an empty rural tile is normal.
                if "empty" in str(exc).lower() or \
                        "no matching features" in str(exc).lower():
                    print(f"      tile {i}/{len(tiles)}: empty")
                    break
                print(f"      tile {i}/{len(tiles)} attempt {attempt+1}: "
                      f"{type(exc).__name__}: {str(exc)[:110]}", flush=True)
                if attempt < retries - 1:
                    time.sleep(5 * (2 ** attempt))
    return parts


def fetch_features(ox, name: str, tags: dict, bbox: dict,
                   retries: int = 3) -> gpd.GeoDataFrame:
    """Whole-bbox first; backoff retries; tile split as fallback.

    Layers listed in TILE_FIRST skip the whole-bbox attempt entirely — for
    those it does not fail, it hangs, and a hang is not retryable."""
    # osmnx >= 2.0 takes bbox as (left, bottom, right, top) = (W, S, E, N).
    box = (bbox["west"], bbox["south"], bbox["east"], bbox["north"])

    if name not in TILE_FIRST:
        for attempt in range(retries):
            try:
                gdf = ox.features_from_bbox(box, tags)
                print(f"    whole-bbox query ok ({len(gdf)} raw features)")
                return gdf
            except Exception as exc:  # noqa: BLE001 - Overpass throws many types
                wait = 5 * (2 ** attempt)
                print(f"    attempt {attempt+1}/{retries} failed: "
                      f"{type(exc).__name__}: {str(exc)[:160]}")
                if attempt < retries - 1:
                    print(f"    backing off {wait}s ...", flush=True)
                    time.sleep(wait)
        print("    falling back to a 2x2 tile split")
        n = 2
    else:
        n = TILE_FIRST[name]
        print(f"    heavy layer — going straight to a {n}x{n} tile split "
              f"({n*n} queries)", flush=True)

    parts = _tiled_fetch(ox, name, tags, bbox, n, retries)
    if not parts:
        raise RuntimeError(f"Overpass failed for layer '{name}' on every path")
    return pd.concat(parts)


def pull_layer(ox, name: str, tags: dict, bbox: dict, force: bool) -> Path:
    out = RAW / f"{name}.parquet"
    if out.exists() and not force:
        g = gpd.read_parquet(out)
        print(f"  cached   {name:<11} {len(g):>6} features  "
              f"({', '.join(sorted(set(g.geom_type)))})")
        return out

    print(f"  querying {name:<11} tags={tags}", flush=True)
    gdf = fetch_features(ox, name, tags, bbox)
    gdf = _sanitize(gdf)
    if "osmid" in gdf.columns:
        before = len(gdf)
        gdf = gdf.drop_duplicates(subset=["osmid"])
        if before != len(gdf):
            print(f"  deduped {before-len(gdf)} features repeated across "
                  f"tile seams")
    RAW.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out)
    counts = gdf.geom_type.value_counts().to_dict()
    print(f"  saved    {name:<11} {len(gdf):>6} features  {counts}")
    return out


def pull_drive_network(ox, bbox: dict, force: bool) -> Path:
    edges_p = RAW / "roads_edges.parquet"
    if edges_p.exists() and not force:
        e = gpd.read_parquet(edges_p)
        print(f"  cached   {'roads':<11} {len(e):>6} edges  "
              f"{e.length.sum():.0f} deg-len")
        return edges_p

    box = (bbox["west"], bbox["south"], bbox["east"], bbox["north"])
    print("  querying roads       network_type=drive (this is the slow one)",
          flush=True)

    def _graph(b, tries=3, wait0=15):
        for a in range(tries):
            try:
                return ox.graph_from_bbox(b, network_type="drive",
                                          simplify=True, retain_all=True)
            except Exception as exc:  # noqa: BLE001
                print(f"      attempt {a+1}/{tries}: "
                      f"{type(exc).__name__}: {str(exc)[:130]}")
                if a < tries - 1:
                    time.sleep(wait0 * (2 ** a))
        return None

    frames = []
    G = _graph(box)
    if G is not None:
        nodes, edges = ox.graph_to_gdfs(G)
        frames.append(edges.reset_index())
    else:
        # The whole-AOI drive graph is by far the heaviest Overpass query we
        # make and it is the one that gets refused. Quadrants are four small
        # queries instead of one huge one; duplicate edges across the seams are
        # dropped by osmid afterwards.
        print("    whole-bbox drive graph refused; splitting into quadrants")
        nodes = []
        for i, q in enumerate(_quadrants(bbox), 1):
            g = _graph(q)
            if g is None:
                print(f"      quadrant {i}: GAVE UP")
                continue
            n, e = ox.graph_to_gdfs(g)
            print(f"      quadrant {i}: {len(e)} edges")
            frames.append(e.reset_index())
            nodes.append(n)
        if not frames:
            raise RuntimeError("Overpass refused the drive network on every "
                               "path — re-run ingest/osm.py later")
        nodes = pd.concat(nodes)

    edges = pd.concat(frames, ignore_index=True)
    if "osmid" in edges.columns:
        before = len(edges)
        edges = edges.drop_duplicates(subset=["u", "v", "key"])
        if before != len(edges):
            print(f"    dropped {before-len(edges)} duplicate seam edges")
    keep = [c for c in ["u", "v", "key", "osmid", "name", "highway",
                        "length", "geometry"] if c in edges.columns]
    edges = edges[keep].copy()
    for c in edges.columns:
        if c not in ("geometry", "length", "u", "v", "key"):
            edges[c] = edges[c].astype(str)
    edges = gpd.GeoDataFrame(edges, geometry="geometry", crs=edges.crs)
    RAW.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(edges_p)
    print(f"  saved    {'roads':<11} {len(edges):>6} edges, "
          f"{len(nodes)} nodes, total length "
          f"{edges['length'].sum()/1000:.1f} km")
    return edges_p


def status() -> None:
    print(f"data/raw/osm/  ->  {RAW}")
    if not RAW.exists():
        print("  (nothing yet)")
        return
    for p in sorted(RAW.glob("*.parquet")):
        g = gpd.read_parquet(p)
        print(f"  {p.name:<24} {len(g):>7} rows  crs={g.crs.to_string()}  "
              f"types={sorted(set(g.geom_type))}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--skip-roads", action="store_true")
    ap.add_argument("--graph", action="store_true",
                    help="ALSO pull the routable drive graph. Slow and often "
                         "refused by Overpass; not needed for P2-T11.")
    args = ap.parse_args()

    if args.status:
        status()
        return

    cfg = load_cfg()
    bbox = cfg["bbox"]
    ox = setup_osmnx()
    print(f"AOI {cfg['id']}  bbox W{bbox['west']} S{bbox['south']} "
          f"E{bbox['east']} N{bbox['north']}")
    print(f"osmnx {ox.__version__}  cache -> {CACHE}\n")

    for name, tags in LAYERS.items():
        if name == "roads" and args.skip_roads:
            continue
        pull_layer(ox, name, tags, bbox, args.force)

    if args.graph:
        pull_drive_network(ox, bbox, args.force)

    print()
    status()


if __name__ == "__main__":
    main()
