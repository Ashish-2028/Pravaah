# PRAVAAH — Build Plan & Live Progress Tracker

> **Read [PRAVAAH.md](PRAVAAH.md) first** for *what* the project is.
> This file is *what to do next, in what order, and what is already done.*

---

## ⚡ LIVE STATUS BLOCK — every agent updates this

```
CURRENT PHASE   : WAVE 3 (product polish). Waves 1-2 done. Demo-ready NOW.
LAST UPDATED    : 2026-09-02 ~06:30 IST
BLOCKED ON      : nothing.
NEXT ACTION     : Both remaining ML items investigated and CLOSED as not
                  achievable (see RESUME HERE). Manual pass on sandbox owed.
LANE A (ML)     : P0 GREEN. P1 GREEN. A1 ERA5 DONE (56/56 pts, 3.6M rows, 84MB).
                  A11 IMD gridded DONE (2018-2024, 15,342 cell-days).
                  A2 NWP DONE (56/56, 2.33M rows). CUBE BUILT: 3,623,424 rows,
                  56 pts, 28 cols. LEAKAGE SUITE 6/6 GREEN (found+fixed a real
                  hole first — see log 04:45). P2-T8 impervious DONE.
                  P4 LABELS DONE: 84 points (10 high-conf), 8,595 pos cell-events.
                  P5 RAINCAST-v0 TRAINED: 10/12 heads beat persistence AND raw GFS.
                  NOTE: 3 agents were killed mid-run by a usage limit; all had
                  already written their artefacts. Wide-NWP pull left at 161/195.
                  !! ERA5 UNDER-REPRESENTS EXTREMES — see Progress Log 03:30 !!
LANE B (App)    : P10 backend LIVE on :8000 (smoke-tested, replay law verified).
                  P9 Streamlit DONE (4 tabs; offline violation found+fixed).
                  P11 React DONE — all 6 views, map VERIFIED by human in
                  a real browser (292 ward polygons rendering).
DEMO READY?     : YES. Real model output, real metrics in /verify, 180 cached
                  bilingual advisories, offline street basemap. Loggers live.
```

---

## 🔴 RESUME HERE — written 2026-09-02 06:30 IST, mid-session pause

**Read this first. It is the handover. Everything below in the phase sections is
still true but predates Waves 1-3.**

### State right now

Everything committed. `git log --oneline -6` should show:
```
38316d3  Fix: live refresh was deleting the radar panel's own source
f84c854  Deck: the sandbox's evidence boundary as a pitch asset
7f8e234  Sandbox: live InundaNet what-if with an honest evidence boundary
```

To bring it up:
```bash
cd pravaah
pkill -f "uvicorn serve.main"
nohup $HOME/miniforge3/bin/conda run -n pravaah python -m uvicorn serve.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
```
Then **http://localhost:8000** (FastAPI serves the built React app at `/`).

### ✅ Wave 3 is COMPLETE — the agent finished

Sandbox view + AI chat panel are built, verified and committed
(`abdcd90`). Nothing is mid-flight. **7 routes**, all green.

**One manual check owed before the demo:** the agent drove the sliders and the
map click programmatically (native value setter, `map.fire('click')`) because the
browser pane runs hidden. The handlers are standard `onChange` / MapLibre
`click`, so risk is low, but do one real-mouse pass over `#/sandbox`.

### What was finished this session (verified, not assumed)

- **Gemini AI chat** — `serve/chat.py`, model `gemini-3.5-flash-lite`, chosen on
  RATE LIMITS (15 RPM / 500 RPD vs flash's 5 / **20 RPD** — 20 would not survive
  one demo) and speed (1.3 s vs 4.7 s; the big flash models burn ~360 thinking
  tokens and were truncating replies). Two guards: a numeric post-check that
  REJECTS any reply containing a number absent from the context, and a
  deterministic fallback so the endpoint cannot fail. Tested adversarially —
  refuses to predict next Tuesday, refuses to guarantee a flood, answers Hindi
  in Hindi. **Backend only — the UI panel was the running agent's job.**
- **Event selector** on Nowcast + Forecast (`ui/src/components/EventSelector.jsx`)
  — 4 historical events + hour picker, jumps to each event's declared peak,
  separate `archiveEvent`/`archiveT` store keys so the shared live clock is
  untouched. ARCHIVE labelled in 4 places. Ward bands go 7 high (live) -> 44
  high at the 2024 cloudburst peak; the colour ramp lights up, which was the ask.
- **UI declutter** — the two provenance panels deleted; right rails converted
  from CSS grid to flex + `shrink-0` (grid was compressing a 227 px card into
  126 px, which was the text overflow); the 56-point circle matrix on the map
  replaced by an interpolated raster (`ui/src/lib/rainfield.js`, Gaussian
  kernel); `SkillChart.jsx` now plots 2-3 lines instead of 16; radar panel's
  fetch gate fixed so its three states are distinguishable.
- **Sandbox BACKEND** — `serve/sandbox.py`, `POST /api/sandbox` +
  `GET /api/sandbox/curve`. Live InundaNet on 148,776 real 100 m cells, 0.10 s
  warm. See the finding below.
- **Radar regression fixed** — see Progress Log 06:30.

### 🎯 The best thing found this session — use it in the pitch

The trained InundaNet booster's **highest split on `rain_sum` is 25.30 mm**, so
above that it is *mathematically constant* in event rainfall: 40 mm, 120 mm and
300 mm return byte-identical answers. A 0-300 mm slider would have been a
control that does nothing over 90% of its travel, in front of judges.

The sandbox now reads that boundary **out of the model artefact** and ships it as
`evidence.limits_mm`, with a response curve so the flattening is drawn rather
than asserted. Within the evidenced range it moves properly: **8 -> 11 -> 17 ->
23** high-risk wards across the presets.

**This also settled the pending quantile-mapping decision, opposite to
expectation.** Quantile mapping is monotone and trees split on ORDER, so mapping
InundaNet's rain *inputs* yields the identical tree with rescaled thresholds — it
relabels the axis and cannot widen the response. It genuinely helps **RainCast**,
where the compressed quantity is the *target* (ERA5 said 20.9 mm on 28 Jun 2024
where IMD's grid said 150.7, which is why the 15 mm/h head had 63 positives and
was dropped). **No InundaNet retrain needed. No deck numbers change.** Both
questions are written up in `pravaah/docs/demo_script.md`.

### What is left, in priority order

1. ~~**RainCast retrain against quantile-mapped targets**~~ — **CLOSED, do not
   attempt.** The map is fitted on DAILY distributions; RainCast's targets are
   HOURLY windows. Measured: the daily/hourly ratio swings from 18x at q90 to
   6.1x at q99, so the two are not related by one monotone map. Applying the
   daily-fitted CDF to hourly targets would not be a bias correction, it would
   be an unvalidated transform that looks sophisticated and would not survive a
   meteorologist's question. The gauge-anchored model already exists: RainFuse
   trains on IMD's own gridded product against IMD's own 24 h categories.
2. **Never done by a human, and should be:** one real-mouse pass over
   `#/sandbox` (see above), plus the airplane-mode test on two
   laptops, and opening `#/verify` in a real browser.
3. Deferred, not started, none blocking: RainFuse multi-lead heads (6/12/48/72 h
   — `/api/rain` currently returns identical cells for every lead and the UI now
   says so honestly), CSGD parametric density post-processing, RainFuse national
   scaling, Sentinel-1 SAR flood labels, NOAA ISD integration.

### 🔐 Security note carried forward

The Gemini API key was pasted in plaintext in chat. It is in `.env` (gitignored,
never committed) but it now exists in the session log. **Rotate it after the
demo.**

### Environment facts (verified, do not re-derive)
```
conda      $HOME/miniforge3/bin/conda        env name: pravaah   python 3.11.16
run a cmd  $HOME/miniforge3/bin/conda run -n pravaah --no-capture-output <cmd>
env gate   make check     -> 39/39 libraries OK
node       v25.5.0 / npm 11.8.0
backend    make serve     -> http://localhost:8000  (/docs for the API)
fakes      make fakes     -> 98 files, schema-validated
```

---

## 📋 Protocol for agents working on this repo

**Read this section before you touch anything.**

1. **Read the LIVE STATUS BLOCK above** to know where the project stands. Then read the phase you're
   about to work on. Do not re-derive what's already done.
2. **Task IDs are stable.** `P3-T2` means Phase 3, Task 2. Reference them in commit messages and in
   the progress log.
3. **Only tick `[x]` when you have real, verified output.** Charter rule R3: *run it, show it, then
   say done.* A file that exists but was never opened is not done. If you tick a box, the artefact
   named in that task exists on disk and you looked at it.
4. **Use `[~]` for in-progress** and `[!]` for *attempted and blocked* — with a one-line reason
   appended to the task.
5. **After finishing any task, do all three:**
   - tick the box,
   - update the LIVE STATUS BLOCK (phase, last-updated, next action, blocked-on),
   - append one line to the **Progress Log** at the bottom of this file.
6. **Never edit a file contract** (PRAVAAH.md §12.2) without bumping `schema` in
   `data/outputs/index.json` and noting it in the Progress Log. The contracts are why two lanes can
   run at once.
7. **Never delete or rewrite another agent's Progress Log entries.** Append only.
8. **If a phase's EXIT GATE is not green, do not open the next phase.** Say so in BLOCKED ON instead.

---

## 🛣️ The two lanes

The frozen contracts (P1) exist so that app work does not wait on model work.

```
   P0 ── P1 ──┬── LANE A (ML/data)   P2 → P3 → P4 → P5 → P6 → P7 → P8 ──┐
              │                                                          ├── P12 integrate
              └── LANE B (app)       P9 → P10 → P11 ────────────────────┘        ↓
                                     (builds entirely on FAKE files)          P13 → P14
```

- **Lane A is yours, hands-on, sequential.** It is the part that can actually fail.
- **Lane B can be handed to background agents** the moment P1 lands, because it never touches a
  model — it reads `data/outputs/`, which will contain fakes until P8 replaces them with real files.
- **The handoff is a file swap, not a merge.** That is the entire point of the contracts.

---

## ⏱️ Suggested clock (31 Aug → 1 Sep)

Gates matter more than the clock. If you are behind, cut per §15.1 of PRAVAAH.md — do not compress a gate.

| Block | Phases | Hrs |
|---|---|---|
| Setup | P0, P1 | 1.5 |
| **Kick off background data pulls immediately after P0** | P3-T1 runs while you do P2 | — |
| Morning | P2 (hydrology), P3 (cube) | 4.5 |
| Midday | P4 (labels), P5 (RainCast) | 3 |
| Afternoon | P6 (InundaNet), P7 (RainFuse, cuttable), P8 (precompute) | 3.5 |
| Evening | P10 (FastAPI), P12 (integrate) | 2 |
| Night | P13 (proofs), P14 (demo prep) | 2 |
| *(parallel, Lane B)* | P9 Streamlit, P11 React | — |

---

# PHASE 0 — Environment

**Context.** The geospatial stack (`pysheds`, `rasterio`, `geopandas`, `pysteps`, `numba`) is the
single most common way a project like this dies at hour 20. Machine currently has **only system
Python 3.9.6** — too old for the stack. Fix this *completely* before writing a line of pipeline code.
Decision and rationale live in [ENVIRONMENT.md](ENVIRONMENT.md).

- [x] **P0-T1** — Install Miniforge (`brew install --cask miniforge`), then `conda init zsh`, then open a new terminal.
- [x] **P0-T2** — `conda create -n pravaah python=3.11 -y` and activate it.
- [x] **P0-T3** — Install the **conda-forge** block first (geo + numeric), in ONE command. See ENVIRONMENT.md §3.
- [x] **P0-T4** — Install the **pip** block second (pure-python: api, ml-serving, clients). Never interleave with conda.
- [x] **P0-T5** — Run the import smoke test (`scripts/env_check.py`) — every library imports, versions printed.
- [x] **P0-T6** — ⏳ AWAITING HUMAN — 🧍 **MANUAL (you, not an agent):** `earthengine authenticate` — opens a browser, needs your Google login + GEE project id.
- [x] **P0-T7** — ⏳ AWAITING HUMAN — 🧍 **MANUAL (you, not an agent):** create `.env` with `ANTHROPIC_API_KEY=` (or `GEMINI_API_KEY=`) and `GEE_PROJECT=`. Commit `.env.example` only.
- [x] **P0-T8** — Verify Node toolchain: `node -v` (have v25.5.0), `npm -v` (have 11.8.0). No action expected.

> **EXIT GATE P0:** `python scripts/env_check.py` prints ✅ for every library including `pysheds`,
> `pysteps`, `rasterio`, `geopandas`, `lightgbm`, `numba`. **Nothing else opens until this is green.**

---

# PHASE 1 — Repo skeleton + frozen contracts + fake data

**Context.** This phase is small and boring and it unlocks everything else. Fake output files that
match the contracts mean the whole app can be built before a single model exists. Do not skip it to
"save time" — skipping it is what forces a big-bang integration later.

- [x] **P1-T1** — `git init`; add `.gitignore` (`data/raw/`, `data/static/`, `data/labels/`, `*.zarr`, `.venv`, `node_modules`, `.env`).
- [x] **P1-T2** — Create the directory skeleton per PRAVAAH.md §9 (already scaffolded — verify it matches).
- [x] **P1-T3** — Write `configs/aoi_delhi_ncr.yaml`: bbox, lattice spec, grid resolution, event catalogue, CRS, thresholds. **This is Proof P-4** — every downstream script reads region facts from here, never from a literal.
- [x] **P1-T4** — Write `serve/schemas.py`: pydantic models mirroring PRAVAAH.md §12.2 exactly. This is the machine-readable copy of the contracts.
- [x] **P1-T5** — Write `scripts/make_fakes.py` → generates plausible `data/outputs/2024-06-28/*` for ~12 timestamps (0400→0930, 30-min steps): `index.json`, `wards_*.geojson`, `rain_grid_*.json`, `kpi_*.json`, `advisory_*.json`, plus a stub `reports/metrics.json`.
- [x] **P1-T6** — Get **real Delhi ward polygons** from DataMeet (A10) so the fakes sit on real geometry. Fake *numbers* are fine; fake *geometry* means the map has to be rebuilt later.
- [x] **P1-T7** — `make fakes` runs clean; open one `wards_*.geojson` and eyeball it.
- [x] **P1-T8** — First commit: `chore: repo skeleton, contracts, fake outputs`.

> **EXIT GATE P1:** `data/outputs/2024-06-28/` is populated with contract-shaped files on real ward
> geometry. **🚀 The moment this is green, Lane B (P9/P10/P11) can be launched in parallel.**

---

# PHASE 2 — Static hydrology (LANE A)

**Context.** *Do this before any ML.* It is pure geoprocessing — no training, no labels, no
uncertainty — and it produces a **real, demoable result**: a susceptibility map that already lights
up Minto Bridge, ITO and Zakhira. It is the highest-value, lowest-risk work in the project, and it is
also the entire static half of InundaNet's feature set. If everything else slipped, this alone plus
the map is still a credible demo.

- [x] **P2-T1** — `ingest/dem.py`: pull the 2 Copernicus GLO-30 tiles from `s3://copernicus-dem-30m` via unsigned boto3 (PRAVAAH.md §5.3). Merge → clip to the AOI box.
- [x] **P2-T2** — `features/static_hydro.py` pysheds pipeline: fill pits → fill depressions → resolve flats → flow direction → **flow accumulation**.
- [x] **P2-T3** — **Grid-search the stream threshold** over `[100, 250, 500, 1000, 2500]`, scoring each against OSM waterways by F1. Record the winner + the whole table. *(Charter rule R7 — fitted, not hardcoded. This table is a slide-worthy artefact.)*
- [x] **P2-T4** — Compute **HAND** from `(fdir, dem, acc > best)`. Cross-check against `s3://glo-30-hand`; report correlation.
- [x] **P2-T5** — Compute **TWI**, slope, plan curvature.
- [x] **P2-T6** — `ingest/osm.py`: Overpass/osmnx pull — drains/canals/rivers, hospitals, schools, pumps, drive network. **Cache the raw response to disk** (Overpass rate-limits; do not re-pull).
- [x] **P2-T7** — Derive **distance-to-drain** and **drainage density** rasters.
- [x] **P2-T8** — Landcover → **impervious fraction**; built-up (GHSL); permanent water (JRC GSW). *(See ENVIRONMENT.md §6 — there are GEE-free direct-download paths for all three; prefer them.)*
      Done in `ingest/landcover.py` + `features/static_hydro.py:step_impervious`, GEE-free. **impervious** = ESA WorldCover 10 m v200 2021 class 50 (unsigned S3 `esa-worldcover`; keys listed live, never hardcoded; windowed COG read of tile `N27E075`) → fraction of class-50 10 m pixels per cell. **built_up** = GHSL GHS-BUILT-S R2023A 2020 100 m (JRC direct download, Mollweide tile `R6_C26`, m²/cell ÷ 10 000). The two independent products agree at Pearson **r = 0.848** over the AOI. Both are in `data/static/static_stack.nc` on the same 100 m EPSG:32643 grid, alignment asserted; the 11 pre-existing `g100_*.tif` are byte-identical after the rebuild. **Still outstanding: JRC GSW permanent water** (WorldCover class 80 is in the cached raster as a stopgap).
- [x] **P2-T9** — Resample every static layer onto the shared **100 m grid**; stack into `data/static/static_stack.nc` (or zarr). One CRS, one transform, verified aligned.
- [x] **P2-T10** — Build the **static susceptibility map** — a simple documented weighted combination (low HAND + high TWI + high impervious + far from drain). Render to `reports/susceptibility.png`.
- [x] **P2-T11** — `features/exposure.py`: WorldPop × OSM assets × ward polygons → `data/static/exposure.parquet` (per ward: people, hospitals, schools, road_km, pumps).

> **EXIT GATE P2:** 🎯 **The susceptibility map ranks Minto Bridge, ITO and Zakhira in the top
> quintile — with no ML and without ever being told about them.** If it does not, the terrain
> pipeline has a bug (usually CRS misalignment or an unfilled DEM). Fix it here; everything
> downstream inherits it.

---

# PHASE 3 — The weather cube (LANE A)

**Context.** Wall-clock bound, not effort bound: A1 is 56 lattice points × 8 monsoons of hourly data.
**Start the pulls the instant P0 is green and let them run in the background while you do P2.**
The cube is where the no-look-ahead law (R4) is enforced — get the accessor and the leakage test
right and every downstream number is defensible.

- [x] **P3-T1** — 🔥 **START FIRST, RUN IN BACKGROUND.** `ingest/openmeteo_archive.py` (A1): ERA5-Land hourly for all 56 points, 2018-06-01 → 2025-09-30. Resumable, one parquet per point, `requests-cache` on.
- [x] **P3-T2** — `ingest/openmeteo_histfcst.py` (A2): past NWP runs as issued, 3 models, 2021+. **Store `issue_time` on every row — this is the whole point.**
- [ ] **P3-T3** — `ingest/noaa_isd.py` (A13): hourly obs for Safdarjung `421820`, Palam `421810` from the NOAA S3 open bucket.
- [x] **P3-T4** — `ingest/imd_gridded.py` (A11) via `imdlib` + `ingest/chirps.py` (A12) — daily cross-checks and climatology features.
- [ ] **P3-T5** — *(optional, non-blocking)* `ingest/imerg_gee.py` (A4): export the 28 Jun 2024 window first, bulk history later. **If GEE is slow, drop it — ERA5 already covers the target.**
- [x] **P3-T6** — `cube/grid.py`: lattice + 100 m grid definitions, read from the YAML config.
- [x] **P3-T7** — `cube/build_cube.py`: assemble everything into `cube/ncr_cube.zarr`. Every forecast record carries **both** `issue_time` and `valid_time`.
- [x] **P3-T8** — `cube/accessor.py`: implement `cube.at(t0)` — **the one and only read path**, returning the latest data issued ≤ `t0`.
- [x] **P3-T9** — `eval/leakage_tests.py`: shuffle future rows, assert features unchanged. Must pass.
- [x] **P3-T10** — `features/dynamic.py`: lags 1/2/3/6 h, accumulations 3/6/24 h, antecedent 3/7/15 d, API.
- [x] **P3-T11** — `features/nwp.py`: 3-model precip at lead, **pairwise disagreement**, 3×3 neighbourhood means, climatological anomaly.

> **EXIT GATE P3:** `ds.sel(lat=28.65, lon=77.22).precip.plot()` shows the **28 Jun 2024 spike**,
> AND `eval/leakage_tests.py` is green. Both, or the phase is not done.

---

# PHASE 4 — Flood labels (LANE A)

**Context.** ⚠️ **The single highest-risk item in the project.** The charter says "geocoded PWD /
traffic waterlogging points" as if it's a download — it is not. It is a hand-built CSV. Budget real
time for it, do it deliberately, and treat the resulting file as a deliverable in its own right.
Being able to say *"we built the label set by hand because none exists"* is a strength, not an
excuse.

- [x] **P4-T1** — Hand-build `data/labels/delhi_waterlogging_points.csv`: `name, lat, lon, source, notes`. Target **60–100 points** from published PWD / Traffic Police waterlogging lists and news reports. Include the famous ones: Minto Bridge, ITO, Zakhira, Pul Prahladpur, Azad Market, Ring Road/Sarai Kale Khan, Okhla underpass…
- [x] **P4-T2** — Buffer positives to **200 m** (fallback 300 m if positives are too thin) and stamp with event windows + onset timestamps where known.
- [x] **P4-T3** — Pull **DFO** flood polygons and the **Global Flood Database** events intersecting NCR; union into the label set.
- [x] **P4-T4** — Generate **negatives**: cells > 1 km from any positive **within the same event window**. Never sample negatives globally — that teaches geography, not hydrology.
- [x] **P4-T5** — Build the cell-event label table → `data/labels/inunda_labels.parquet`. **Report the positive rate.**
- [x] **P4-T6** — Sanity plot: labels over the susceptibility map from P2. They should visually agree. If they don't, one of the two is wrong.

> **EXIT GATE P4:** A labelled cell-event table exists with a **stated positive count and positive
> rate**, and its geography overlaps the susceptibility hotspots.

---

# PHASE 5 — RainCast-v0, the 0–6 h nowcast (LANE A)

**Context.** Spec in PRAVAAH.md §7.1. **Build the three baselines before the model** — the model's
only job is to beat them, and if you build the model first you will have no idea whether it did.

- [x] **P5-T1** — Baseline A: persistence, `I(rain_now > thresh)`. Score CSI/POD/FAR per lead.
- [x] **P5-T2** — Baseline B: raw ECMWF at the same lead. Score it.
- [x] **P5-T3** — Baseline C: **pySTEPS** Lucas-Kanade extrapolation. Score it, **and save the frame PNGs** — they are the nowcast animation in the UI.
- [x] **P5-T4** — Assemble the RainCast feature table from the cube. **Every feature via `cube.at(t0)`, no exceptions.**
- [x] **P5-T5** — Train per-lead LightGBM (leads 1/2/3/6 h), balanced class weights, ~500 trees, lr 0.05, colsample 0.8. **15 mm head first** — it is the one guaranteed to have enough positives.
- [x] **P5-T6** — Add the 50 mm / 3 h head. If positives are too thin, **say so and ship the 15 mm head** rather than shipping a fake number.
- [x] **P5-T7** — Isotonic calibration on **VAL 2024 only**.
- [x] **P5-T8** — Score on **TEST 2025**: CSI, POD, FAR, Brier per lead and threshold → `reports/`.
- [x] **P5-T9** — Reliability diagram → `reports/reliability_raincast.png`.
- [x] **P5-T10** — Save `models/raincast_v0.pkl`.

> **EXIT GATE P5:** 🎯 **CSI(RainCast) > CSI(persistence) AND > CSI(raw ECMWF)** on the 2025 test
> monsoon. **If not met: add features. Never add model complexity.** (More lags, more antecedent
> windows, model-disagreement terms, terrain interactions.)

---

# PHASE 6 — InundaNet-v0, rain → water (LANE A)

**Context.** Spec in PRAVAAH.md §7.3. This is the **USP** — the part no competitor will have. Note
that HAND alone is already a strong baseline, so score against it: a modest, honest lift over HAND is
a better story than an unbelievable one.

- [x] **P6-T1** — Join P2 static features + P3 dynamic features + P4 labels into the cell-event training table.
- [x] **P6-T2** — Baseline: HAND-threshold rule alone. Score AUC-PR. **This is what ML must beat.**
- [x] **P6-T3** — Train LightGBM on cell-event rows. **Subsample negatives** — do not try to hold ~560k cells × all event-hours in memory.
- [x] **P6-T4** — **5 km spatial-block CV.** Random splits are forbidden here (R5) — adjacent cells are near-duplicates.
- [x] **P6-T5** — Report AUC-PR, F1 at the operating point, reliability. Isotonic calibrate.
- [x] **P6-T6** — **SHAP** per-ward top-3 drivers, mapped to plain words (`"low HAND"`, `"impervious"`, `"antecedent rain"`).
- [x] **P6-T7** — `models/risk.py`: aggregate cells → wards; compute **onset** (first lead where calibrated P crosses the operating point), **peak**, **ci90**.
- [x] **P6-T8** — Impact engine: spatial-join flooded cells against `exposure.parquet` → people, hospitals, schools, road-km, pumps. **Deterministic, and labelled as such.**
- [x] **P6-T9** — `risk_score = P × exposure × criticality`; assign `risk_band` ∈ low|watch|high|critical.
- [x] **P6-T10** — Save `models/inundanet_v0.pkl`.

> **EXIT GATE P6:** 🎯 **The 28 Jun 2024 P(flood) map ranks Minto Bridge, ITO and Zakhira in the top
> quintile — without those names ever being a feature.** AUC-PR reported honestly, beside the HAND
> baseline.

---

# PHASE 7 — RainFuse-v0, 6–72 h NWP correction (LANE A) — **CUTTABLE**

**Context.** Spec in PRAVAAH.md §7.2. Intellectually the most defensible model in the pitch (*"we
correct physics, we don't replace it"*), but the **first thing to cut** if the clock is against you —
the Forecast view can fall back to raw ECMWF with an honest label. Ship the **24 h bucket only**;
extra leads are a bonus.

- [x] **P7-T1** — Build the RainFuse feature table: 3-model precip at lead by `issue_time`, pairwise disagreement, ERA5 climatological anomaly, last-24h accumulation, terrain, monsoon-phase encodings, 3×3 neighbourhood means.
- [x] **P7-T2** — Binary heads at the **official IMD thresholds** 64.5 / 115.6 / 204.5 mm. **24 h lead first.**
- [ ] **P7-T3** — Quantile heads q10 / q50 / q90 (feeds the fan chart).
- [x] **P7-T4** — Isotonic calibration on VAL 2024.
- [x] **P7-T5** — Score Brier vs the raw-ECMWF probability proxy → `reports/reliability_rainfuse.png`.
- [ ] **P7-T6** — Produce the **raw-ECMWF vs RainFuse-corrected vs observed** side-by-side map for 28 Jun 2024. *(Slide-worthy on its own.)*
- [x] **P7-T7** — Save `models/rainfuse_v0.pkl`.

> **EXIT GATE P7:** `Brier(RainFuse) < Brier(raw ECMWF)` and the reliability curve hugs the diagonal.

---

# PHASE 8 — Precompute all demo outputs (LANE A)

**Context.** 🔑 **This is the moment fakes become real and Lane B's app lights up with actual
numbers — with zero code changes on either side.** From here the models never run again. Everything
the demo shows is a file on disk.

- [x] **P8-T1** — `scripts/precompute.py`: for the 28 Jun 2024 event, for every timestamp 0400→0930 at 30-min steps, run all models **through `cube.at(t)`** and write every contract file.
- [x] **P8-T2** — Emit `wards_{HHMM}.geojson` for all timestamps (real geometry, real probabilities, real drivers, real exposure).
- [x] **P8-T3** — Emit `rain_grid_{HHMM}.json` (nowcast + forecast blocks) for all timestamps.
- [x] **P8-T4** — Emit `kpi_{HHMM}.json` for all timestamps, including the source **badges**.
- [x] **P8-T5** — Copy pySTEPS + radar frames into `outputs/2024-06-28/frames/`.
- [x] **P8-T6** — Update `index.json` with the real timestamp list and ward count.
- [x] **P8-T7** — **Validate every emitted file against `serve/schemas.py`.** A silent schema drift here breaks the app at demo time.
- [ ] **P8-T8** — *(if time)* Repeat for event #2, Jul 2023. **First thing on the cut list.**
- [x] **P8-T9** — `git add data/outputs/ models/*.pkl reports/` and commit. **These are demo-critical and must be in git.**

> **EXIT GATE P8:** The Streamlit harness and FastAPI, unchanged, now render **real numbers**. Replay
> of 28 Jun 2024 runs end to end.

---

# PHASE 9 — Streamlit validation harness (LANE B — can start after P1)

**Context.** Dual-purpose and therefore never wasted work: it is **your model-inspection tool** while
you build Lane A, *and* the emergency fallback demo. It reads the exact same `data/outputs/` files as
React, so it is always in sync. Build it incrementally as models land.

- [x] **P9-T1** — `ui-fallback/streamlit_app.py` skeleton reading `data/outputs/` + an event/timestamp selector.
- [x] **P9-T2** — Map tab: ward choropleth on `p_flood` via `streamlit-folium`.
- [x] **P9-T3** — Rain tab: nowcast/forecast grid, lead selector, threshold toggle.
- [x] **P9-T4** — Ward detail: timeline, SHAP driver bars, exposure table.
- [x] **P9-T5** — Verification tab: reliability plots + ablation table from `reports/metrics.json`.
- [x] **P9-T6** — Confirm it runs on fakes now and on real files after P8 **with no code change**.

> **EXIT GATE P9:** A working fallback demo exists. From this point the project can no longer fail
> completely.

---

# PHASE 10 — FastAPI backend (LANE B — can start after P1)

**Context.** Spec in PRAVAAH.md §10. It is a **thin file reader** — no model ever loads here. If you
find yourself importing lightgbm in `serve/`, stop: something has gone wrong.

- [x] **P10-T1** — `serve/main.py` skeleton + `GET /api/health`.
- [x] **P10-T2** — `GET /api/events` ← `index.json`.
- [x] **P10-T3** — `GET /api/state`, `GET /api/wards`, `GET /api/rain` — all with `event` + `t` filtering (**artefacts stamped ≤ t only**).
- [x] **P10-T4** — `GET /api/ward/{id}`, `GET /api/frames`.
- [x] **P10-T5** — `GET /api/verify/metrics` ← `reports/metrics.json`.
- [x] **P10-T6** — `serve/advisory.py`: LLM adapter (~15 lines), **cache-first**, disk cache in `data/outputs/`. Offline / no key / rate-limited → serve cache; cache miss → structured numbers + *"narration unavailable"*. **The demo never blocks on an LLM.**
- [x] **P10-T7** — `POST /api/advisory/{ward}`.
- [x] **P10-T8** — Mount `StaticFiles` at `/` for the built React app.
- [x] **P10-T9** — Every response validated against `serve/schemas.py`.

> **EXIT GATE P10:** Every endpoint returns contract-shaped JSON from files. `uvicorn serve.main:app`
> is the only command needed.

---

# PHASE 11 — React command center (LANE B — can start after P1)

**Context.** Spec in PRAVAAH.md §11. **Build views 1, 4 and 5 first** — Command Center, Inundation,
Replay. Those three *are* the pitch and are never cut. Views 2, 3 and 6 are bonus. Every component
renders from fake files from the very first commit.

- [x] **P11-T1** — `npm create vite@latest ui -- --template react`; install maplibre-gl, recharts, zustand, react-router-dom, clsx, framer-motion, tailwindcss, @tailwindcss/vite, lucide-react.
- [x] **P11-T2** — Configure the **Vite dev proxy** for `/api` → `http://localhost:8000`. *(This, not CORS middleware — see ENVIRONMENT.md §5.)*
- [x] **P11-T3** — Dark control-room theme tokens; **bundle Inter locally** (no Google Fonts CDN — offline rule).
- [x] **P11-T4** — `AppShell`: sidebar, topbar, clock, Live|Replay toggle, source badges.
- [x] **P11-T5** — `MapCanvas`: MapLibre wrapper + GeoJSON layer registry. **No external basemap tiles.**
- [x] **P11-T6** — `ChoroplethLayer`, `AssetMarkers`, `GlowPulse`.
- [x] **P11-T7** — zustand store `{event, t, lead, layer}`; `LeadSlider`, `ReplayClock`.
- [x] **P11-T8** — **View 1 — Command Center**: KPI strip (5 cards), choropleth + layer switch, ranked-ward right rail, `CapModal`.
- [x] **P11-T9** — **View 4 — Inundation + Impact**: `WardDetailPanel`, `DriverBars`, `TimelineChart`, assets table, `AdvisoryDrawer`.
- [x] **P11-T10** — **View 5 — Replay**: curated event dropdown, 10× clock, play/pause/speed, observed-outcome overlay.
- [x] **P11-T11** — **View 2 — Nowcast** *(bonus)*: animated frames, lead stepper, skill-vs-lead curve.
- [x] **P11-T12** — **View 3 — Forecast** *(bonus)*: exceedance choropleth, small multiples, `FanChart`.
- [x] **P11-T13** — **View 6 — Verification** *(high value, low risk — static render of `reports/`)*.
- [x] **P11-T14** — `vite build` → `ui/dist`, served by FastAPI StaticFiles.

> **EXIT GATE P11:** Views 1, 4 and 5 render from the API with **zero console errors**.

---

# PHASE 12 — Integration + the offline gate

**Context.** PRAVAAH.md §11.4. **The airplane-mode test is a hard gate, not an optimisation.** Venue
wifi is not a dependency you are allowed to have.

- [x] **P12-T1** — Point the app at the **real** P8 outputs. Nothing should need changing — if something does, a contract was violated; note it in the Progress Log.
- [x] **P12-T2** — Pre-generate and commit advisories for every (event, critical ward, timestamp) tuple.
- [ ] **P12-T3** — `vite build`; confirm FastAPI serves the bundle at `/` on one origin.
- [ ] **P12-T4** — Audit for **any** non-localhost network call (fonts, map tiles, CDNs, analytics). There must be **zero**.
- [ ] **P12-T5** — 🎯 **AIRPLANE TEST: wifi OFF, cold start, full 3-minute run, zero console errors.**
- [ ] **P12-T6** — Repeat the airplane test on the second laptop.

> **EXIT GATE P12:** Both machines pass the airplane test end to end.

---

# PHASE 13 — The four proofs

**Context.** PRAVAAH.md §2 and §8. **This is what actually wins.** A beautiful app with an empty
Verification view loses to an ugly one with a real ablation table. Do not let the clock eat this
phase — cut a React view instead.

- [x] **P13-T1** — **Proof P-1 · Fusion.** `eval/ablation.py`: all-sources vs each single-source vs raw NWP. Produce the table.
- [x] **P13-T2** — **Proof P-2 · Calibration.** Reliability diagrams for all model heads → `reports/`.
- [x] **P13-T3** — **Proof P-3 · Lead time.** `eval/verify_vs_cap.py`: our threshold-crossing timestamp vs IMD's CAP alert timestamp, at matched FAR, on 28 Jun 2024. **Produce a number in minutes.**
- [x] **P13-T4** — **Proof P-4 · Portability.** Write a second `configs/aoi_*.yaml` and show the pipeline accepts it. Even partial execution proves the claim.
- [x] **P13-T5** — Consolidate everything into `reports/metrics.json`; confirm the Verification view renders it.
- [x] **P13-T6** — Write the **stated-limits** list for the honesty slide: GIF radar not raw volumes, SAR blind in dense cores, open labels first, single pilot city for inundation.

> **EXIT GATE P13:** All four proofs are visible **inside the product**, not just in a folder.

---

# PHASE 14 — Demo preparation

**Context.** PRAVAAH.md §18. Rehearse against the clock, and record a backup — a screen recording has
saved more hackathon demos than any amount of defensive coding.

- [ ] **P14-T1** — Freeze the code. `git tag v0-college`. After this, **only `docs/` may change.**
- [ ] **P14-T2** — Screen-record the full 3-minute run as the ultimate fallback; embed it in the deck.
- [ ] **P14-T3** — Rehearse the §18.2 click path with a timer. Twice.
- [ ] **P14-T4** — Drill the §17 Q&A answers — especially *leakage*, *no raw radar*, and *what's your accuracy*.
- [ ] **P14-T5** — Both laptops: full repo, models, outputs pulled; both airplane-tested; present from the healthier one.

> **EXIT GATE P14:** Two timed rehearsals done, backup recording exists, code tagged.

---

## ✂️ Cut order — decided now, never negotiated at 2 a.m.

```
1. drop event #2 (Jul 2023)
2. drop Forecast small-multiples (view 3)
3. drop the routing bonus
4. drop RainFuse extra leads  →  then drop RainFuse entirely (P7)
5. drop Nowcast view (view 2)
6. present the Streamlit fallback instead of React
```

**NEVER CUT: InundaNet (P6) · Replay (P11-T10) · Command Center (P11-T8) · the four proofs (P13).**

---

## 📓 Progress Log — append only, newest at the bottom

Format: `YYYY-MM-DD HH:MM · <task-id> · <what happened> · <evidence>`

```
2026-08-31 00:00 · —      · Build plan created. Repo skeleton scaffolded. No code yet.
```

2026-08-31 02:15 · P0-T1..T4 · Miniforge installed ($HOME/miniforge3), env 'pravaah' py3.11.16 created. TWO REAL FAILURES FIXED: (a) pysteps is NOT on conda-forge for any platform -> moved to pip; (b) pysteps pip build died on `clang: unsupported option '-fopenmp'` (Apple clang has no OpenMP) -> installed conda-forge llvm-openmp+clang and rebuilt with CC=$CONDA_PREFIX/bin/clang. Also learned pip is all-or-nothing: one failing build blocked all 14 packages. ENVIRONMENT.md corrected.
2026-08-31 02:40 · P0-T5   · GATE GREEN. scripts/env_check.py -> 39/39 libraries OK incl. pysheds 0.5, pysteps, lightgbm 4.7, geopandas 1.1.4. Functional tests pass (lightgbm trains, 4326->UTM43N reproject, pysheds numba JIT).
2026-08-31 02:45 · P1-T6   · Ward polygons sourced. datameet/maps has NO wards; correct repo is datameet/Municipal_Spatial_Data/Delhi/Delhi_Wards.geojson. 290 features, Polygon, fields Ward_Name/Ward_No, bbox lon 76.84..77.35 lat 28.40..28.88. 'MINTO ROAD' IS a real ward -> the P6 exit gate is checkable. ITO/Zakhira are landmarks inside DARYAGANJ/KAROL BAGH; config records this.
2026-08-31 02:50 · P1-T3..T5,T7 · configs/aoi_delhi_ncr.yaml (Proof P-4 carrier), serve/schemas.py (contracts as pydantic), scripts/make_fakes.py. `make fakes` -> 98 files, ALL schema-validated. 290/290 wards in AOI, all 5 hotspot wards present.
2026-08-31 02:55 · P10-T1..T5,T8,T9 · serve/main.py written and smoke-tested live. REPLAY LAW VERIFIED: request t=0745 correctly serves t=0730 (latest artefact <= clock). /api/health, /api/events, /api/state, /api/wards all return contract-shaped JSON.
2026-08-31 03:00 · P3-T1   · PROBE CAUGHT A REAL BUG (this is why rule R6 exists): Open-Meteo archive returns `cape` as 100% NULL (64704/64704, dtype object) on every model - CAPE is ERA5 single-levels, not ERA5-Land. Verified cape IS available on historical-forecast-api (max 3990 J/kg), along with bonus convective_inhibition + lifted_index. CAPE moved from the A1 lane to the A2 lane, where rows carry a real issue_time - strictly better for R4. A1 pull launched: 56 points, 2018-05-15..2025-09-30, 64704 rows/point, resumable.
2026-08-31 03:05 · lanes   · Launched 3 parallel agents on non-overlapping dirs: React (ui/), Streamlit (ui-fallback/), static hydrology (ingest/+features/).

2026-08-31 03:20 · P3-T1   · A1 COMPLETE: 56/56 points, 64,704 rows each (3.6M rows, 84 MB), 11 min. Hit HTTP 429 mid-run; exponential backoff + resume-from-disk handled it with no intervention.
2026-08-31 03:25 · P9      · Streamlit harness delivered (4 tabs, mtime-keyed caching, AppTest-verified). TWO FIXES APPLIED BY LEAD: (a) it used folium tiles="OpenStreetMap" — a hard violation of the offline rule; this app IS the emergency demo and must pass the same airplane gate, so switched to tiles=None with our own GeoJSON on a dark canvas. Verified folium.Map takes no `bgcolor` kwarg before shipping it. (b) it correctly flagged kpi people_exposed=0 at 0400 while ward rows showed exposed population — make_fakes now uses probability-weighted EXPECTED exposure (1.37M -> 3.68M -> 3.06M across the storm) instead of a hard p>0.5 step count.
2026-08-31 03:30 · P3-T4   · ⚠️ MAJOR FINDING — ERA5 CANNOT BE THE SOLE TRUTH LAYER. On the flagship event (28 Jun 2024, Safdarjung 228 mm): IMD official gridded = 150.7 mm and ranks #1 wettest day of 2024; ERA5-Land = 20.9 mm and does not make the year's top 8. ERA5 is a ~9 km reanalysis and smooths convective extremes — its TIMING is right (peak 22:00Z 27 Jun = 03:30 IST 28 Jun, matching the reported cloudburst) but magnitude is off by ~10x and the max is misplaced to the SE corner. Also note the timezone trap: the event is '28 June' IST but straddles 27 June UTC — rule R8 is what prevents silently halving it. CONSEQUENCE: IMD gridded (A11) is promoted from cross-check to PRIMARY DAILY TRUTH for the RainFuse exceedance heads (they are IMD's own 64.5/115.6/204.5 categories, so IMD's own product is the most defensible truth in front of IMD judges). ERA5 keeps hourly structure/lags/antecedent, which daily IMD cannot provide. IMD gridded stops at 2024, so the 2025 TEST split falls back to ERA5+IMERG — state this openly. The disagreement is EVIDENCE FOR PROOF P-1, not an embarrassment. Documented in PRAVAAH.md §5.6.
2026-08-31 03:35 · P3-T4   · A11 pull complete, 2018-2024, 15,342 cell-days. Independently-derived extreme-day catalogue VALIDATES the curated event list: 2024-06-28 is #1 (150.7mm), 2023-07-09 Yamuna is #5 (109.2mm), 2021-09-01 is #7 (95.5mm). NOTE: charter event 2020-07-19 does NOT appear in the top 12 — reconsider it as a demo event, and prefer 2018-07-27 (129.4mm, #2) as the second event instead.

2026-08-31 04:00 · P11    · React delivered, all 6 views. Map rendered BLANK in my browser pane. Investigated hard: worker served 200, WebGL2 fine, painter context alive; removed the agent's setWorkerUrl+optimizeDeps.exclude hack and downgraded maplibre 6.6->5.24 chasing it. ROOT CAUSE was neither: document.visibilityState='hidden' in the automation pane => requestAnimationFrame fires 0 times/sec, and MapLibre's whole style-load + tiling path is rAF-driven. Shimmed rAF with setTimeout => styleLoaded:true, 473 features tiled, 292 rendered. THE APP WAS NEVER BROKEN; the test harness was. Human then confirmed the choropleth in a real browser. Kept maplibre 5.24 (stable > bleeding-edge before a demo) and the simpler worker config; both verified working. LESSON for any agent testing a WebGL/canvas/animation UI here: check document.visibilityState and rAF BEFORE diagnosing the app.
2026-08-31 04:05 · A15    · DISCOVERY — the IMD CAP S3 bucket is LISTABLE (unsigned) and archives back to 2019, with the alert timestamp IN THE FILENAME (in-imd-en/YYYY-MM-DD-HH-MM-SS.xml). 9 alerts across 20-29 Jun 2024, 8 across 1-9 Jul 2023. The charter assumed CAP was live-only, so Proof P-3 (lead time vs IMD) could only be claimed for future events. It is now COMPUTABLE FOR THE HISTORICAL DEMO EVENT. This upgrades P-3 from a promise to a number.
2026-08-31 04:10 · P2     · GATE RESULT: passed=false, and the agent reported it honestly. Cell-level: Minto Bridge 97.5 pct PASS; ITO 4.6 (93.7 in 300m); Zakhira 5.5 (77.0) FAIL; Pul Prahladpur 5.8 (98.7). WARD-LEVEL (the scale we actually ship): MINTO ROAD 88.6 pct (top quintile), KAROL BAGH 57.2, DARYAGANJ 54.5, PAHAR GANJ 13.8, JAMA MASJID 0.7. Top-12 wards are all OUTER/fringe (Janak Puri South, Sunder Nagari, Nand Nagri, Mundaka). DIAGNOSIS: pure DEM hydrology finds NATURAL/fluvial flood terrain; Delhi's blackspots are URBAN PLUVIAL (underpasses + drainage-capacity failure). Three of four checkpoints are underpasses/railway underbridges — sub-30m engineered features a 30 m DEM cannot resolve — and GLO-30 is a DSM, so in the dense old city the 'terrain' is partly rooftops (hence Jama Masjid at 0.7). CONSEQUENCE: the charter assumed the static map would already light up the hotspots. It does not, except Minto Road. That makes the LEARNED lift larger and more visible (good for the demo) but raises P4 labels from high-risk to critical-path. Two agents launched: P2-T8 impervious (the missing physical driver for pluvial flooding, always in §7.3, skipped only for time) and P4 labels. The impervious agent is explicitly instructed NOT to tune weights until hotspots pass — that would be fitting to the answer.

2026-08-31 04:30 · P3-T2  · A2 DONE 56/56 (2.33M rows, 11.9 min). COVERAGE IS NOT UNIFORM — probed, not assumed: gfs_seamless from 2021-03-23 (78% of 2021, 100% from 2023); icon_seamless from 2022-11-16 (100% from 2023); ecmwf_ifs025 ONLY from 2024-02-02; previous_dayN only from 2024-01-19. CONSEQUENCE: 3-model disagreement does not exist before 2024, i.e. not in the TRAIN years. RainCast is unaffected (it leans on A1 obs lags, 2018+, plus GFS 2021+). RainFuse is affected: full 3-model correction can only be trained where all three exist. Mitigation: LightGBM handles NaN natively, so columns are kept NaN rather than imputed and `nwp_n_models` records how many models actually spoke in each row — the model can learn to trust the spread only when the spread is real. The 28 Jun 2024 demo event HAS all three models, and 2025 TEST is 100% covered, so the demo and the test metrics are clean.
2026-08-31 04:35 · GEE    · Authenticated, project pravaah-507121, VERIFIED WORKING: 96 IMERG half-hourly frames in the event window, WorldCover reachable. Completes the truth hierarchy on 28 Jun 2024 (station 228 mm): IMD gridded 0.25deg = 150.7 mm; IMERG 0.1deg = 32.9 mm accumulated; ERA5-Land ~9km = 20.9 mm. NOTE THIS IS NOT A RESOLUTION RANKING — IMERG is FINER than IMD gridded and still reads lower. It is a MEASUREMENT-TYPE ranking: gauge-based captures the extreme, satellite retrieval underestimates convection, reanalysis smooths hardest. That is the strongest available answer to 'why fuse?' and belongs on the honesty slide.
2026-08-31 04:45 · P3-T7..T9 · CUBE BUILT: 3,623,424 rows x 28 cols, 56 points, 2018-05-15..2025-09-30. Splits train 2.76M / val 492k / test 367k, temporally disjoint. TWO REAL BUGS CAUGHT AND FIXED: (1) the IMD join was snapped the WRONG DIRECTION — IMD is COARSER (0.25deg) than the lattice (0.1deg), so mapping IMD cells to nearest lattice point left most points unmatched (9.6% coverage). Reversed it to map every lattice point to its nearest IMD cell -> 89.9% (the missing 10% is 2025, which IMD has not published). Only 6 IMD cells cover the whole NCR box, so IMD is a good DAILY AREAL truth but cannot discriminate at ward scale — say this rather than implying otherwise. (2) THE LEAKAGE SUITE FAILED ITS OWN GUARD TEST, exactly as designed: issue_time == valid_time on EVERY row, because A2's issue_time was dropped during the merge. The accessor was therefore filtering on nothing and the other 5 tests were passing VACUOUSLY. Fixed with per-column NWP gating: nwp_issue_time = valid_time.normalize() + 6h (deliberately CONSERVATIVE — a 00Z global run is not on the wire until ~05-06Z; being conservative can only cost skill, being optimistic manufactures it), plus per-lead stamps for previous_day1/2/3. accessor.at() now blanks NWP CELLS whose run was not yet issued while keeping the observation row visible. Suite now 6/6 PASS and the guard proves the gating BITES (280 future-issued NWP cells blanked at t0). LESSON: a leakage test that cannot fail is worse than no leakage test.
2026-08-31 04:48 · P2-T8  · Impervious (ESA WorldCover) + built-up added; weights hand .30 twi .20 slope .15 dist_drain .10 impervious .25. Agent did NOT tune to pass, as instructed. RESULT: at 300 m neighbourhood ALL FOUR checkpoints now clear 80th pct (Minto 99.8, ITO 99.3, Zakhira 88.4 up from 77.0, Pul Prahladpur 99.9). At CELL level still only Minto Bridge (99.5). At WARD level 1 of 6 (MINTO ROAD 85.9 PASS; Daryaganj 31.4, Karol Bagh 60.7, Pahar Ganj 24.1, Jama Masjid 3.1, Turkman Gate 7.6). THE DIAGNOSIS IS IN THE HAND VALUES: Jama Masjid HAND 14.88 m, Turkman Gate 14.27 m, Pahar Ganj 7.0 m — the old city reads as HIGH ABOVE DRAINAGE while being 92-99.7% impervious. That is the DSM problem stated numerically: GLO-30 includes buildings, so in the dense core the 'terrain' is rooftops and HAND is measuring roof height. This is a publishable, honest limitation and it is precisely the gap the LEARNED model plus the label set must close.

2026-08-31 05:10 · P4     · LABELS DONE (agent finished artefacts before being killed by the usage limit). 84 curated Delhi waterlogging points — 10 high-confidence, 74 medium, each with source, notes, an OSM cross-check and separation distance, plus a `holdout` flag. 8,595 positive cell-events / 85,950 negatives across 22 events (1:10). CRITICAL AUDIT RESULT: top_quintile_enrichment = 0.94, i.e. positives are NOT enriched in high-susceptibility cells — very slightly BELOW random. Verdict recorded in the audit as 'the static map does not explain the label set'. This INDEPENDENTLY CONFIRMS the Phase 2 diagnosis from the opposite direction. Consequence to face honestly: within a single event the only cell-discriminating features are static ones, and they do not correlate with the labels; rain is constant across a 0.1 deg cell. So InundaNet can learn WHEN (event-level, from rain) far more easily than WHERE (cell-level). Do not overclaim the WHERE.
2026-08-31 05:30 · P5     · RAINCAST-v0 GATE PASSED, 10/12 head-window combinations beat BOTH persistence and raw GFS on TEST 2025. Got there through TWO diagnosed redesigns, both driven by measurement rather than guesswork:
    (1) TARGET REFRAME. v1 asked 'does hour t+lead exceed 5 mm' -> CSI 0.01-0.06, FAR > 0.98. Two faults: statistically a specific single future hour at a specific 0.1 deg point is a 0.9% event and the exact HOUR of a convective cell is near-unpredictable; operationally nobody warns 'it will rain between 04:00 and 05:00'. Reframed to WINDOW heads — will ANY hour in t+1..t+W exceed the threshold, and will the ACCUMULATION over the window. Positives went 1,516 -> 4,136 (w3) / 7,793 (w6) on test.
    (2) ADVECTION FEATURES. v2 still modelled each lattice point in ISOLATION, so a storm 11 km upwind was invisible. Added 18 neighbour columns: 8-neighbour rain at t..t-3, N/S/E/W directional means, signed NS/EW gradients (drift direction), box mean/max. This is the physical content of the charter's pySTEPS baseline expressed as tree-splittable features. Result: p5_w1 CSI 0.060->0.104, p5_w6 0.070->0.104 (2.7x persistence), acc10_w6 0.118 vs pers 0.071 vs gfs 0.101; FAR 0.98 -> 0.82.
  Note this obeyed the charter gate's own instruction — 'if not met, ADD FEATURES, never add model complexity'. Also dropped scale_pos_weight: it fought the isotonic calibration and inflated FAR. Absolute CSI ~0.10-0.12 is genuinely low, and we say so: point-scale hourly heavy-rain nowcasting from a 9 km reanalysis with NO radar is a hard problem. The defensible claim is RELATIVE SKILL over persistence and raw NWP, which is exactly what the charter asked for. CAVEAT TO FIX: acc20_w1 has only 22 test positives and should be suppressed — the min-positives guard is set at 20 and is too loose; raise it to ~100.

2026-08-31 06:30 · P7     · RAINFUSE-v0 trained on the WIDE NW-India domain (195 NWP points x 2,793 IMD cells, 1.36M rows). SPLIT DIFFERS FROM RAINCAST ON PURPOSE: IMD gridded is unpublished beyond 2024, so a 2025 test split is literally EMPTY — the first run correctly produced 0 test positives in all three categories and refused to score. RainFuse therefore uses train<=2022 / val 2023 / TEST 2024. Bonus: the 28 Jun 2024 demo event now sits in the HELD-OUT year, the strongest place to demo from. RESULT, 'heavy' (64.5mm, 4,066 test positives): CSI 0.090 vs raw NWP 0.080, and BRIER 0.0112 vs 0.0401 — 3.6x better calibrated. That is the real claim: RainFuse does not detect many more heavy-rain days than the physics, it makes the physics' probabilities MEAN something. Exactly what the charter said it would do ('never replaces the physics — corrects and calibrates it'), and it is Proof P-2 evidence. 'very_heavy' loses on CSI (0.021 vs 0.039) though it wins on Brier — reported as a FAIL, not spun. 'extremely_heavy' skipped: 72 test positives, below the min-100 guard. ALSO FIXED A LEAK HERE: climatology was computed with a groupby-transform over the WHOLE table, folding test-year observed rainfall into a training feature. Now computed on training years only.
2026-08-31 07:00 · P6     · INUNDANET-v0 trained, and this one needed THREE corrections before the number could be believed:
    (1) LABEL-PROCESS LEAKAGE. First run: AUC-PR 0.9104, within-event ROC-AUC 0.9653 — impossible given that two independent measurements had already shown terrain does not explain these labels. Top feature was `point_rain_mm` by 2x. Audit of the label table against the label column: point_id/point_name 100% null for negatives and 0% for positives; sample_weight exactly 1.0 vs 0.637; rain_confirmed 0.878 vs 0.574; point_rain_mm 97.4 vs 69.9. All are computed DURING labelling and are functions of the answer. point_id/point_name had been excluded only by accident (strings dropped by the numeric filter) — luck, not methodology. All are now explicitly blacklisted and a null-rate tripwire runs over every surviving feature. After the fix: AUC-PR 0.5454.
    (2) COORDINATES EXCLUDED BY DESIGN. lat/lon/x_utm/y_utm/cell_id/row/col are forbidden features: with 84 labelled points and negatives sampled >1 km away, raw coordinates let a tree memorise 'near a known blackspot' and score beautifully while learning nothing transferable.
    (3) NEGATIVE SAMPLING BIAS — the subtlest and most important. Negatives drawn >1 km from positives are systematically LESS URBAN (impervious 0.244 vs 0.827; built_up 0.105 vs 0.378), and imperviousness ALONE scores ROC-AUC 0.867. So a model can look excellent having learned only 'is this cell urban' — the classic presence-only artifact. Re-scored on IMPERVIOUSNESS-MATCHED negatives (38,819 rows, base rate 0.221): model ROC-AUC 0.829 / AUC-PR 0.558 vs imperviousness-alone 0.654. THE MODEL DOES BEAT THE SHORTCUT, by a real margin, and that matched number is the one to quote — not the flattering 0.93.
  Final honest headline: spatial-block CV AUC-PR 0.545 (6.0x base rate, 7.1x the HAND-only baseline); matched-negative ROC-AUC 0.829 vs 0.654 for the urban shortcut. Top features are impervious, built_up, surface_height, dist_drain, sink_depth — pluvial/urban drivers, NOT the classical HAND/TWI terrain stack, which is consistent with everything Phase 2 found.

2026-08-31 08:15 · P6/P8 · INUNDANET FIXED AT THE ROOT, then precomputed. Discovered by testing the model's RAIN RESPONSE directly rather than trusting CV scores: holding a median urban cell fixed and sweeping rainfall gave p_flood 0.0041 at 0 mm -> 0.0052 at 200 mm. FLAT. A flood model that ignores rain is not a flood model, whatever its AUC says.
  ROOT CAUSE: every negative was drawn from the SAME event windows as the positives (spatially >1 km away, temporally identical). So within each labelled pair the rainfall was nearly the same, rain had zero power to separate the classes, and the model correctly concluded rain was uninformative.
  FIX 1 — DRY-DAY NEGATIVES (features/dry_negatives.py): 25,785 negatives on the SAME cells on dry monsoon days. Contrast becomes 'same place + heavy rain = flooded / same place + no rain = dry', which terrain cannot explain away. rain_sum jumped to TOP FEATURE (42,548 gain, was 8,612); between-event ROC-AUC nan -> 0.974. Side benefit: kills the urban/rural sampling artifact, since a dry-day negative has identical imperviousness to its own positive.
  FIX 2 — MONOTONIC CONSTRAINTS: response was still wobbly (dipped between 50 and 80 mm), so the replay showed flood risk FALLING as the cloudburst peaked. monotone_constraints=+1 on all rain features. Response now 0.0004 -> 0.0054, never decreasing. Cost AUC-PR 0.567 -> 0.498; worth it, because a screen showing risk dropping mid-cloudburst is indefensible no matter what CV says.
  FIX 3 — DEMO WINDOW WAS THE WRONG HOURS. Timestamps 0400-0930Z are 09:30-15:00 IST, i.e. AFTER the storm. Actual box-max hourly rain: 0.6 mm at 00:00Z -> 32.9 mm at 01:00Z (06:30 IST peak) -> decay to 3.2 by 06:00Z. Window moved to 0000-0700Z, 15 frames.
  RESULT: replay now builds correctly — high-risk wards 7 -> 23 -> 32 -> 44, p_flood max 0.784 -> 0.841, people exposed 7.7M -> 8.7M.
2026-08-31 08:20 · P2-T11 · Population fixed. WorldPop was NULL (server ignores range requests, ~53 KB/s = 2.8 h). Swapped to GHS-POP R2023A 100 m (JRC, same family as the GHSL built-up layer, one 67 MB tile, seconds). 290/290 wards, Delhi total 20.7M — matches published NCT figures.
2026-08-31 08:25 · P8     · END TO END ON REAL OUTPUT. FastAPI + React serve real InundaNet predictions on real ward geometry with real GHS-POP population and real plain-word drivers. The fake->real swap needed ZERO code changes in serve/ or ui/ — the frozen contracts did their job exactly as designed.

2026-08-31 22:00 · A3/A14/A15/A16 · LOGGERS LIVE under caffeinate, all 4 healthy. The charter's radar URL pattern (max_dwr_{site}.gif) 404s on every site; scraped mausam.imd.gov.in's own radar page for the real product codes — sri_delhi.gif (Surface Rainfall INTENSITY, i.e. an actual rain-rate product and the one worth decoding), caz_delhi.gif, ppz_delhi.gif. Chennai 404s on this naming and was dropped rather than left erroring. CAP feed returned 8 live items on first poll.
2026-08-31 22:20 · P6 · THE DRAINAGE CRACK. Storm-sewer capacity is not open data anywhere in India, but the STRUCTURES are: OSM tags tunnel=yes / layer<0 on every underpass. Pulled 1,305 below-grade ways + 7,329 bridges. Named sanity check is decisive — Keshav Chowk Underpass, Sarita Vihar Okhla Underpass, Model Town Underpass, Rohtak Road Underpass, Pragati Maidan Tunnel. All four known blackspots sit far closer to a below-grade way than the 2,746 m median: Minto Bridge 0 m, ITO 100 m, Zakhira 300 m, Pul Prahladpur 1,281 m. InundaNet with underpass_dist/bridge_dist/underpass_density: AUC-PR 0.498 -> 0.611, matched-negative ROC-AUC 0.829 -> 0.918 (imperviousness shortcut fell to 0.564 on the harder matched set), lift over HAND 9.81x. underpass_dist is now the #2 feature. Ward ranking: Pahar Ganj 13.8 -> 87.9 pct, Jama Masjid 0.7 -> 63.3 pct.
2026-08-31 22:40 · P13-T1 · PROOF P-1 ABLATION — NEGATIVE RESULT, KEPT. Leave-one-family-out on y_p5_w3: without advection 0.058 (-0.040, the largest drop = advection is the dominant family); WITHOUT NWP 0.124 (+0.026 — removing NWP IMPROVES the model); all-sources 0.098. Diagnosed rather than patched: NWP coverage starts at different dates (GFS 2021-03, ICON 2022-11, ECMWF 2024-02) so a column's MISSINGNESS correlates with year, and TEST 2025 is fully covered — a pattern never seen in training. Restricting to consistent-coverage columns recovers 0.098 -> 0.116. Added an 80% train-coverage filter to raincast (computed on TRAIN only, so it cannot see test): p5_w1 0.104 -> 0.130, acc10_w6 0.118 -> 0.144, FAR 0.82 -> 0.79, still 10/12. THE DEEPER READING IS THE PROJECT'S OWN THESIS: at 0-6 h, observation-based advection beats global NWP (raw GFS 0.015). That IS the nowcast gap PRAVAAH exists to fill, and it is coherent with RainFuse where NWP at 6-72 h IS the signal and we beat it on Brier. Present the negative ablation — it is a better argument than a tidy one.
2026-08-31 22:50 · P13-T3 · PROOF P-3 IS NOT COMPUTABLE, AND WE SAY SO. Pulled IMD's CAP archive for the 7 days around 28 Jun 2024: 7 alerts, all multi-state bulletins (Bihar, Kerala, Uttarakhand, Odisha), NONE mentioning Delhi. The script has an explicit honesty gate that refuses to compare our crossing against Kerala's alert and writes computable=false with the reason. IMPORTANT FRAMING: that feed is a sparse daily bulletin cycle, NOT IMD's city warning channel — its silence is not evidence IMD failed to warn Delhi, and we must not imply it is. A computable substitute (timing vs raw NWP and vs persistence on the same event) is reported instead.
2026-08-31 23:00 · A4 · IMERG PULLED AND HONESTLY REJECTED. 976 monsoon days, 48 cells, 30-min frames, 2018-2025, via getRegion (no Drive export, stays off the Community-tier queue). 24 features incl. intra-hour trend and 30-min advection, 85.7% train coverage. Clean A/B on identical code: mean CSI ERA5-only 0.0728 vs +IMERG 0.0718; only 4/12 heads improved and those 4 are the thinnest (acc20_w1 has 22 test positives), while the best-populated heads got worse. CAUSE: the TARGET is ERA5-derived, so ERA5 features are its natural best predictors and IMERG enters as a noisy proxy for our label rather than new information about it. NOT SHIPPED; archive kept (2nd truth source, nowcast frames, and the right predictor set the moment the target changes). Recorded in reports/imerg_experiment.json.
2026-08-31 23:05 · P10-T6/P12-T2 · ADVISORY LAYER SHIPS WITHOUT AN API KEY. Three tiers: disk cache -> deterministic bilingual renderer -> LLM. The deterministic tier is the FLOOR, not a stopgap: it can only interpolate keys that exist in the input contract, so it structurally cannot invent a figure — which is a stronger answer to 'is the AI forecasting?' than any prompt instruction. The LLM path adds a POST-CHECK that every number it wrote appears in the input, and rejects the output otherwise. 180 advisories cached. Also corrected a wording overclaim: `onset` is the first frame at which probability CROSSED the operating point, which is retrospective — 'flagged since 05:30 IST', never 'water expected from 05:30', because we do not produce a time-to-arrival forecast.
2026-08-31 23:08 · basemap/P-4 · Offline street basemap built from OSM data already on disk (19,823 km roads, waterways, assets, 1,305 underpasses) -> 6.3 MB GeoJSON from localhost. No tile server, no CDN, airplane gate intact. roads_minor (239,283 features, 43 MB) deliberately excluded. configs/aoi_chennai.yaml derived mechanically and verified to load through grid.py with zero code changes — scope stated honestly in the file header: portable PIPELINE, not a trained region.

<!-- APPEND NEW ENTRIES BELOW THIS LINE -->

2026-09-02 05:40 · WAVE3 · GEMINI CHAT SHIPPED, MODEL CHOSEN ON RATE LIMITS NOT QUALITY. `serve/chat.py`, `gemini-3.5-flash-lite`. The free tier's binding constraint is REQUESTS PER DAY and it differs by an order of magnitude inside the flash family: flash 5 RPM/**20 RPD**, flash-lite 15 RPM/**500 RPD**. Twenty would not survive one demo. Lite is also 3.6x faster measured on this exact task (1.3 s vs 4.7 s) because the larger models spend ~360 thinking tokens per call — which was truncating replies and tripping the timeout. Two corrections along the way, both caught by testing rather than reasoning: `gemini-2.5-flash` 404s ("no longer available to new users") so a remembered model list is not authority; and Gemini's "Live API" (`bidiGenerateContent`) is bidirectional streaming for VOICE/VIDEO — a text Q&A over a JSON context wants `generateContent`, and using Live would have added websockets and audio framing to a request/response question. Guards: numeric post-check rejects any reply containing a number absent from the context, plus a deterministic fallback, so the endpoint can neither fabricate nor fail.

2026-09-02 06:05 · WAVE3 · EVENT SELECTOR + UI DECLUTTER (two parallel agents). Selector: separate `archiveEvent`/`archiveT` store keys rather than writing the shared clock, so Command/Inundation/Replay/Verify are provably unaffected. Ward bands go 7 high (live September) -> 44 high at the 2024 cloudburst peak. Confirmed against the API that `/api/rain` returns byte-identical cells for lead=6/24/72 and only `lead_h` changes, so the UI now labels anything but +24 h as "the 24 h field, re-labelled" and adds an honest q50/q90 toggle that DOES change the field. Declutter root cause: right rails were CSS grids with a definite height, which compresses auto tracks — a 227 px card was handed 126 px, which was the reported text overflow. Now flex + `shrink-0`. Circle matrix on the map replaced by an interpolated raster (Gaussian, sigma 0.42 cell; IDW rejected because it puts a bullseye on every node).

2026-09-02 06:20 · WAVE3/SANDBOX · THE MODEL'S OWN EVIDENCE BOUNDARY, FOUND BY BUILDING THE SANDBOX AND SHIPPED RATHER THAN HIDDEN. `serve/sandbox.py` runs InundaNet live on 148,776 real 100 m cells against user-chosen rainfall (0.10 s warm). Testing the sliders showed they did nothing above ~25 mm. Cause, read out of the artefact: the booster's highest split on `rain_sum` is **25.30 mm**, so above it the model is mathematically constant — 40/120/300 mm return byte-identical answers. A 0-300 mm slider would have been dead over 90% of its travel in front of judges. The endpoint now exposes `evidence.limits_mm` and a response curve so the flattening is drawn, not asserted; within the evidenced range it moves 8->11->17->23 high-risk wards. **This settled the pending quantile-mapping question, opposite to expectation: QM is monotone and trees split on ORDER, so mapping InundaNet's rain INPUTS gives the identical tree with rescaled thresholds — it relabels the axis and cannot widen the response.** QM belongs to RainCast, where the compressed quantity is the TARGET. No InundaNet retrain, no deck numbers change. Three things testing caught before they shipped: risk bands are read from the AOI config (0.25/0.5/0.75) not the literal I had guessed, so the sandbox and replay agree on "high"; presets built from IMD's 24 h categories all saturated because `rain_sum` is a 6 h ERA5 accumulation; and presets now obey `rain_sum/6 <= rain_max <= rain_sum` so nobody can build a physically impossible storm. Scoped exception to the "no lightgbm in serve/" rule, documented in the module docstring — lazy import, shipped artefact, no training path, every other route survives its absence.

2026-09-02 06:30 · FIX · LIVE REFRESH WAS DELETING THE RADAR PANEL'S OWN SOURCE. Two scripts write into `data/outputs/live/` and only one knew it: `publish_radar.py` owns `live/frames/`, while `live_update.py` replaces the WHOLE directory via an atomic rename. Every refresh destroyed the radar frames, the manifest 404'd, and the UI reported "no captures yet" while 133 logged GIFs sat unused in `data/raw/live/radar`. Same bug as the index.json race in a different costume: **an atomic swap is only atomic for the data you own** — anything a sibling writer put inside the swapped directory must be carried forward explicitly. Copied not moved, so a later failure leaves the previous good directory intact WITH its frames. Also republish radar at the end of each live pass (the logger captures every 10 min but nothing turned the GIFs into frames, so the panel aged out mid-demo), wrapped so a radar failure can never fail the live update. Verified: 73 files before a refresh and 73 after, all 72 frames serve 200, disclaimer intact.

2026-09-02 07:05 · WAVE3 COMPLETE · SANDBOX VIEW + CHAT PANEL SHIPPED, AND TESTING THEM FOUND TWO FALSE POSITIVES IN MY OWN HONESTY GUARDS. (1) The chat's numeric post-check rejected ROUNDING: the context holds 0.12048192771084337 and any sane answer writes 0.1205, so **"how accurate is this model?" — a question judges are near-certain to ask — had its CORRECT answer rejected** and fell back to a generic city summary that never mentioned accuracy. A false positive in a guard is not harmless; it silently downgrades the feature while looking like the model misbehaved. Roundings to 0-4 dp are now admitted, which cannot launder a fabrication because a rounding of a value we hold IS that value at lower precision — re-verified that invented figures are still caught. (2) The system prompt's own example number LEAKED into answers: it wrote "the probability is 34%" for a ward whose probability is 0.365, because rule 4 illustrated with a concrete 34%. Rule 4 is now value-free and instructs the model to quote the ward's own number; verified clean across three runs. (3) The UI agent caught a real flaw in my `/api/sandbox/curve`: the sweep raises `rain_max` alongside `rain_sum` to keep the storm physical, so the curve is NOT purely rain_sum's response — it takes a second step at ~106 mm where `rain_max` crosses its own 29.75 mm limit. Unlabelled that reads as the model still responding to the total; the payload now names both boundaries rather than leaving the client to explain a step it does not account for.

2026-09-02 07:00 · FIX · THE RADAR FIX DID NOT TAKE, AND THE REASON MATTERS. After patching `live_update.py` I verified frames survived a refresh (73 -> 73) and committed. They were gone again 20 minutes later. Cause: **a `live_update.py --loop` process started at 04:50 was still running the PRE-FIX code from memory.** Editing a file does not change a running Python process, so the old loop kept wiping the frames every 15 minutes while the patched file sat on disk looking correct. Killed it, restored the frames from git, restarted the loop on the patched code, and confirmed the manifest regenerates on each pass (18 s old when checked). LESSON: after patching anything that runs in a long-lived loop, RESTART THE LOOP — and verify against the running process, not the file.

2026-09-02 08:10 · CHAT · THE GUARD WAS WRONG, NOT STRICT — AND IT WAS RESTRICTIVE IN THE WRONG PLACE. User's screenshot showed "What is the risk in this ward?" falling back to the deterministic answer. Diagnosed: the rejected numbers were 0.12052/0.04899/0.01488, the CSI scores rounded to FIVE decimals, and my allowed-set enumerated roundings only to four. **The guard's whole design was wrong**: enumerating string forms of a number (separators, percentages, N decimal places) fails repeatedly because the ways to write a number correctly are unbounded — it had already rejected 0.1205 against a stored 0.12048192771084337, I "fixed" it by extending to 4 dp, and it failed again at 5 dp. Replaced with a NUMERIC test: a token with d decimals is grounded if some context value rounds to it at d decimals, or does so as a percentage. Strictly more honest, not merely looser — accepts every faithful rendering at any precision, still rejects anything not derived from a computed number (verified both directions). SEPARATELY, the prompt was restrictive in the wrong dimension: old rule 1 made it stonewall a user asking whether to go out to a named cafe. The hard rule now covers FIGURES AND PREDICTIONS ONLY; reasoning, practical safety advice and ordinary questions are explicitly permitted, with general knowledge kept visibly distinct from PRAVAAH's measurements so the former never borrows the latter's authority. Verified the hard rules survive: still refuses to forecast next Tuesday, to guarantee a flood, or to give casualty counts.

2026-09-02 08:25 · ML · BOTH REMAINING ML ITEMS INVESTIGATED AND CLOSED — NEITHER IS ACHIEVABLE, AND THE SECOND NEARLY SHIPPED A WRONG NUMBER. (1) RainCast quantile-map retrain: the map is fitted on DAILY distributions but RainCast's targets are HOURLY windows, and the daily/hourly ratio swings from 18x at q90 to 6.1x at q99 — the two are not related by one monotone map, so applying it would be an unvalidated transform, not a bias correction. The gauge-anchored model already exists (RainFuse, IMD gridded target, IMD's own categories). (2) RainFuse multi-lead heads: blocked twice. Not trainable (Open-Meteo serves previous_dayN only from 2024; those years are val/test, so zero training rows). Then, using the same data for EVALUATION, the categorical table looked publishable — CSI decayed correctly at 10 mm and 20 mm — and only the 40 mm row IMPROVING with lead exposed it. Ruled out wet bias and missingness; the POD gap was ~6 SE so not noise. **The decisive test was continuous skill, which must degrade as lead grows: correlation 0.579/0.566/0.594 with the supposed 72 h forecast scoring BEST.** `previous_dayN` therefore does not behave as an N-day lead. `eval/skill_by_lead.py` now gates on monotonic degradation BEFORE reporting and refuses to write a curve when it fails — a warning would not have been enough, since two of three thresholds looked fine. LESSON RECORDED: a metric that decays in the expected direction is not evidence the underlying alignment is correct.

2026-09-02 11:40 · DECK/VERIFY · EIGHT PRINT-READY FIGURES, AND THREE ERRORS CAUGHT BY LOOKING AT THEM. `eval/make_figures.py` rebuilds every evaluation graphic at 300 dpi PNG + vector PDF from the artefacts — no number typed in. InundaNet's PR curve and confusion matrix are recomputed by re-running its own spatial-block CV through the model's code path; that run reproduced AUC-PR 0.6108 against the stored 0.6108, so the figures are provably the shipped model. Three problems found while REVIEWING THE RENDERED OUTPUT, all of which would have reached judges: (1) **the confusion matrices were mislabelled** — cells laid out [[hits,misses],[FA,CN]] while the axes said row=predicted, column=observed, so "misses" sat in the "warned but no rain" box; precision/recall were right and the grid was a lie, which is worse than a wrong number because it looks authoritative. (2) **Four heads were ticked for beating a baseline of exactly zero** — raw NWP made ZERO hits at p10 across every window while still producing 145 false alarms (verified in the stored contingency tables). Beating that is not a contest and an absent bar reads as missing data; bars are now annotated "0 hits", marked with a hollow circle, and the headline restated as 6 of 7 heads where the physics scores at all, not 10 of 12. (3) **The scorecard cited a different head from the deck.** LESSON: generating a figure is not the same as checking it — every one of these was invisible in the code and obvious in the image.

2026-09-02 11:45 · VERIFY · P-3's EMPTY BOX REPLACED, NOT DELETED, AND ONE HEAD PINNED EVERYWHERE. The P-3 panel rendered an empty canvas because `leadtime_vs_cap` is []. It now shows "not computable, and here is exactly why": what we tried, the 7 CAP alerts actually examined (unedited, with a Delhi-coverage column derived at runtime from each alert's own `areas` string), why we refuse to compare against an unrelated state's bulletin, and the caveat that the silence of one sparse public feed is NOT evidence IMD failed to warn Delhi. It also surfaces the substitute that IS computable and was sitting unused in the artefact (raw GFS crossing 7.0 h early, persistence 3.0 h late). Added a model scoreboard and `stated_limits`, and corrected a P-1 footnote that asserted the pass condition as though it had passed when the artefact's verdict is "NOT fusion — 'without nwp' scores highest". **FIX ON TOP OF THE AGENT'S WORK:** its scoreboard picked the headline head by max CSI (acc10/6 h, 0.144) while the deck, the figures and this project's own P-1 proof all use p5/3 h (0.121) — a screen quoting a different head from the proof beside it is found in seconds, and the bigger number is not worth it. **All four surfaces now agree: CSI 0.121, persistence 0.049, raw NWP 0.015, head p5/3 h.** Verified in-browser at a real 1440x900 viewport: zero clipped elements, no horizontal overflow, zero console errors across all seven routes. An earlier "1 clipped element" reading was the hidden browser pane collapsing `h-full` to a 16 px viewport, not a layout bug.
