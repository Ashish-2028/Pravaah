# PRAVAAH — Master Project Document

**Predictive Rainfall, Accumulation and Vulnerability Analytics for Anticipatory Hazard response**

An AI/ML-based integrated heavy-rainfall early-warning and inundation-prediction system built from
satellite, radar, ground-observation and NWP model data.

> *Pravaah* (Hindi: **प्रवाह**, "flow"). One pipeline that turns satellite, radar, station and NWP
> streams into calibrated, ward-level rainfall and inundation probabilities — with onset time and
> human impact — for any district in India, open-data-first.

---

## 0. How to use this document

This file is the **single source of truth** for the PRAVAAH codebase. It is written to be read by a
human or by an AI agent / agentic IDE working on the repository with zero prior context.

**If you are an AI agent working on this project, read this before writing any code.** Specifically:

| If you are about to… | Read first |
|---|---|
| Pull or parse any data source | §5 (Data layer), §14 (Rule 6: fetch once, inspect, then parse) |
| Touch the feature table / training data | §6 (Fusion cube), §14 (Rule 4: the no-look-ahead law) |
| Train or modify a model | §7 (Models), §8 (Evaluation), §14 (Rule 7: no hardcoded constants) |
| Write or change an output file | §12.2 (Frozen file contracts) — **these schemas are contracts, never edit unilaterally** |
| Write backend code | §10 |
| Write frontend code | §11 |
| Touch the LLM layer | §13 (the LLM narrates, it never predicts) |
| Decide what to build next | §15 (Build order and phase gates) |

Two rules that override everything else:

1. **The demo never touches the internet.** All model outputs are precomputed to static files and
   committed. The backend is a file reader. (See §10.)
2. **No look-ahead, ever.** Every forecast record carries both `issue_time` and `valid_time`, and
   there is exactly one read path into the data cube. (See §6.3.)

---

## 1. The problem

**Problem statement:** SIH26071 — Ministry of Earth Sciences (MoES) / India Meteorological
Department (IMD).
**Theme:** Software / Disaster Management.
**Ask:** AI/ML-based prediction of heavy rainfall and consequent inundation, using satellite, radar,
observational and NWP model data, with enough lead time for authorities to act.

### 1.1 The four gaps PRAVAAH exists to close

| Gap | What it means operationally |
|---|---|
| **The 0–6 hour hole** | Numerical Weather Prediction (NWP) models run on fixed cycles and take hours to produce output. In the window that matters most for an urban cloudburst — the next 1 to 6 hours — there is effectively no skilful, fine-grained public guidance. |
| **Warnings are district-scale** | An IMD warning says "Delhi: heavy rain". A control room needs "Minto Bridge underpass, 78% probability, water by 06:30". District-level colour codes cannot be actioned at the ward level. |
| **Rain ≠ flood** | A millimetre number is not a decision. 50 mm on a low-lying, sealed, poorly-drained cell with saturated soil floods; the same 50 mm two streets uphill does not. Nobody converts the rain forecast into *water on the ground* and then into *who is affected*. |
| **Data is siloed** | Satellite, radar, gauge and model data live in separate systems with separate formats, cadences and access regimes. No one fuses them into a single learnable representation. |

### 1.2 Why Delhi NCR is the pilot

India's two best urban flood-warning systems are **iFLOWS-Mumbai** and **CFLOWS-Chennai**. Both are
excellent. Both took **years** to build, both required a **bespoke bathymetry survey** of the city's
drainage, and both cover exactly **one city each**.

Delhi NCR — a **30-million-person** capital region with a documented, repeating urban-flooding
problem — **has neither**. It also has, uniquely:

- The best open waterlogging labels in the country (Delhi PWD and Delhi Traffic Police publish
  named, recurring waterlogging locations — Minto Bridge, ITO, Zakhira, Pul Prahladpur…).
- A rich, well-documented event catalogue (see §5.4).
- A public IMD radar site (Delhi DWR) whose imagery is openly polled.

**Pilot region box:** `76.85–77.65 °E, 28.30–28.95 °N`
(0.80° longitude × 0.65° latitude ≈ **78 km × 72 km**).
The **rainfall layer is nationwide** — it is grid-based and region-agnostic. Only the **inundation
layer** is Delhi-specific, because inundation needs per-city terrain and labels.

### 1.3 The two-sentence pitch

> India's best flood-warning systems exist in two cities, and each took years and a bespoke
> bathymetry survey. PRAVAAH stands up ward-level, probabilistic, impact-aware warning for **any
> Indian district from free open data in hours**, and fills the **0–6 hour nowcast gap** those
> systems do not cover.

---

## 2. What winning looks like — the four proofs

Judges are not convinced by "we used AI". They are convinced by **checkable artefacts**. Every task
in this project exists to produce one of four proofs. If a task does not serve a proof or the live
demo, it is out of scope.

| # | Proof | The artefact that proves it | Produced by | Shown in |
|---|---|---|---|---|
| **P-1** | **Fusion works** | An **ablation table**: the all-sources model beats every single-source model *and* beats the raw NWP forecast on CSI / POD / FAR | `eval/ablation.py` | Verification view |
| **P-2** | **Calibration is real** | A **reliability diagram**: when PRAVAAH says 80%, it rains / floods about 80% of the time | `models/calibrate.py` | Verification view |
| **P-3** | **Lead time is gained** | **Minutes gained** over IMD's own public CAP alert stream, at matched false-alarm ratio | `eval/verify_vs_cap.py` | Headline slide |
| **P-4** | **It is portable** | A **new region = one YAML config file**. No bathymetry survey, no field campaign, no manual digitisation | `configs/aoi_*.yaml` | Pitch + Q&A |

**These four proofs are the definition of done.** A beautiful UI with no ablation table loses. An
ablation table with no UI loses. The minimum viable win is credible first versions of all four.

---

## 3. Glossary — domain terms an agent will hit immediately

| Term | Meaning |
|---|---|
| **Nowcasting** | Very-short-range forecasting, 0–6 h, driven mainly by extrapolating current observations rather than by physics simulation. |
| **NWP** | Numerical Weather Prediction — physics simulation of the atmosphere (ECMWF IFS, NOAA GFS, DWD ICON, IMD NCUM/BharatFS). Runs on fixed cycles; skilful from ~6 h out. |
| **`issue_time`** | When a forecast was *produced*. The critical field for leakage prevention. |
| **`valid_time`** | The moment the forecast is *about*. |
| **Lead time** | `valid_time − issue_time`. A 24 h lead means "issued 24 hours before the thing it predicts". |
| **DWR** | Doppler Weather Radar. IMD operates a network; raw volume scans are gated, imagery (GIF) is public. |
| **MAX-Z / SRI** | Radar products. MAX-Z = maximum reflectivity column; SRI = Surface Rainfall Intensity. |
| **IMERG** | NASA GPM Integrated Multi-satellitE Retrievals for GPM. Satellite rainfall at 0.1° / 30 min, global, 2000–present. |
| **ERA5-Land** | ECMWF's reanalysis — a physically-consistent, gridded "best estimate of what actually happened", hourly, 1940–present. Used here as the **training target / answer key**. |
| **CAPE** | Convective Available Potential Energy — atmospheric instability. High CAPE means thunderstorms can build. |
| **DEM** | Digital Elevation Model — a raster of ground height. Here: Copernicus GLO-30 at 30 m. |
| **HAND** | Height Above Nearest Drainage. For every cell, how far vertically it sits above the nearest stream it drains into. **The single strongest predictor of urban inundation.** Low HAND = water collects here. |
| **TWI** | Topographic Wetness Index = `ln(flow_accumulation / tan(slope))`. High TWI = large upslope area feeding a flat cell = wet. |
| **Flow accumulation** | How many upstream cells drain through this cell. Derived from the DEM via flow-direction routing. |
| **Impervious fraction** | Share of a cell that is sealed (concrete, asphalt, roof). Sealed ground does not absorb; it routes water downhill fast. From ESA WorldCover / GHSL. |
| **API (in hydrology)** | Antecedent Precipitation Index — weighted sum of recent rain. Saturated soil floods faster. *(Not to be confused with a web API.)* |
| **SAR** | Synthetic Aperture Radar (Sentinel-1). Sees through cloud — the correct instrument for flood mapping. Optical (Sentinel-2) is cloud-blind exactly when it floods. |
| **CSI / POD / FAR** | Contingency-table skill scores. POD = hits/(hits+misses) — did we catch it? FAR = false alarms/(hits+false alarms) — how often did we cry wolf? CSI = hits/(hits+misses+false alarms) — the balanced score for rare events. |
| **Brier score** | Mean squared error of a probability forecast. Lower is better. Decomposes into reliability + resolution + uncertainty. |
| **Reliability diagram** | Plot of predicted probability vs observed frequency. A perfectly calibrated model lies on the diagonal. |
| **Isotonic regression** | A monotonic, non-parametric calibration map fitted on held-out data that bends raw model scores onto the diagonal. |
| **SHAP** | Shapley Additive exPlanations — per-prediction feature attributions. Turns "78%" into "because low HAND (0.31), impervious (0.18), antecedent rain (0.12)". |
| **CAP** | Common Alerting Protocol — the international XML standard for public alerts. IMD publishes its official alerts as CAP on a public S3 bucket. This is our lead-time benchmark. |
| **Ward** | The smallest municipal administrative unit. Delhi has ~250. The unit at which the product delivers. |
| **Ablation** | Systematically removing one input family at a time and re-measuring skill, to prove each family contributes. |
| **Spatial-block CV** | Cross-validation where folds are contiguous spatial blocks (here 5 km), not random cells. Adjacent grid cells are highly correlated; random splits leak and fake the score. |
| **pySTEPS** | Open-source library for probabilistic precipitation nowcasting by optical-flow extrapolation. Requires no training — our honest baseline and our animation source. |

---

## 4. System architecture

```
┌─────────────────────── FIVE SOURCE FAMILIES ───────────────────────┐
│                                                                     │
│  SATELLITE      RADAR        GROUND OBS      NWP          STATIC    │
│  IMERG          IMD DWR      NOAA ISD        ECMWF IFS    DEM/HAND  │
│  (GPM, 30min)   GIF frames   Safdarjung      GFS          WorldCover│
│  ERA5-Land      (10 min)     Palam           ICON         GHSL      │
│  CHIRPS                      (hourly)        (0-72h)      WorldPop  │
│  IMD gridded                                              OSM       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │  every source is an ADAPTER emitting
                              │  ONE shared record shape:
                              │  (source, variable, valid_time,
                              │   issue_time, geometry, value, quality)
                              ▼
                 ┌────────────────────────────┐
                 │      FUSION CUBE           │   xarray + zarr
                 │  0.1° hourly rain lattice  │   ONE read path:
                 │  100 m inundation grid     │   cube.at(t0)
                 │  + automated leakage test  │   → latest issued ≤ t0
                 └─────────────┬──────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
  ┌───────────┐          ┌───────────┐          ┌────────────┐
  │ RainCast  │          │ RainFuse  │          │ InundaNet  │
  │  0–6 h    │          │  6–72 h   │─────────▶│ rain→water │
  │ nowcast   │          │ NWP corr. │  rain    │  100 m     │
  │ LightGBM  │          │ LightGBM  │  inputs  │  LightGBM  │
  └─────┬─────┘          └─────┬─────┘          └──────┬─────┘
        └──────────────────────┴────────────────────────┘
                               ▼
                 ┌────────────────────────────┐
                 │  ISOTONIC CALIBRATION      │  fitted on VAL year only
                 │  + operating-point search  │  maximise CSI at
                 └─────────────┬──────────────┘  acceptable FAR
                               ▼
                 ┌────────────────────────────┐
                 │      IMPACT ENGINE         │  deterministic, and we
                 │  flooded cells × exposure  │  say so out loud
                 │  → people, hospitals,      │  geopandas spatial join
                 │    schools, road-km, pumps │  ranking + onset time
                 └─────────────┬──────────────┘
                               ▼
              ┌────────── PRECOMPUTED STATIC FILES ──────────┐
              │  data/outputs/{event}/*.json / *.geojson     │  (committed)
              └──────────────────────┬──────────────────────┘
                                     ▼
        ┌────────────────────────────────────────────────────┐
        │  FastAPI  (thin file reader, zero model inference)  │
        └───┬─────────────┬─────────────┬──────────────┬─────┘
            ▼             ▼             ▼              ▼
      React command  Streamlit     LLM advisory   Verification
        center       validation    (narrates      view (the
      (6 views)      harness /     numbers only)  four proofs)
                     fallback
```

**Figure 1 (in the deck) is this diagram.** Say it out loud to judges as: *five open source
families, one honesty law (`issue_time`), three models, one command center.*

### 4.1 The adapter principle — the most important architectural sentence

> Every source box is an **adapter** emitting one shared record shape:
> `(source, variable, valid_time, issue_time, geometry, value, quality)`.
> The open feed used in the prototype can be replaced by the **IMD-native feed** — raw DWR volumes,
> the IMD AWS gauge archive, NCUM/BharatFS grids — **with no change downstream**.

This is said to the judges verbatim. It converts our biggest weakness (we do not have agency access)
into a design choice: *approvals upgrade the system without rework, and each one lands as exactly one
new ablation row.*

### 4.2 Technology by layer

| Layer | Technology |
|---|---|
| **Ingest + loggers** | Python: `requests`, `openmeteo-requests`, `boto3` (UNSIGNED), `osmnx`, `earthengine-api`; `cron` / `caffeinate` |
| **Fusion cube** | `xarray` + `zarr`; 0.1° hourly lattice (rain), 100 m grid (inundation); single latest-at-`t0` accessor + automated leakage test |
| **Models** | `lightgbm` (all three v0 models), `pysteps` (no-training nowcast baseline + animation), `scikit-learn` isotonic regression, `shap` |
| **Hydrology** | `pysheds` (pit-fill → flow direction → accumulation → HAND), `rasterio` / `rioxarray`, `geopandas`, `shapely` |
| **Impact + risk** | `geopandas` spatial join against the exposure table; ranking; onset / time-to-critical |
| **Backend** | FastAPI + uvicorn; serves precomputed files from `data/outputs/`; LLM advisory endpoint with disk cache |
| **Frontend** | React 18 + Vite, MapLibre GL, Recharts, Tailwind, react-router, zustand; dark control-room theme; offline build served by FastAPI `StaticFiles` |
| **Validation harness / fallback** | Streamlit + `streamlit-folium`, single page, reading the **same** `data/outputs/` files |
| **Ops** | Loggers on an always-on machine (`caffeinate -is`) + GitHub Actions cron mirror; `health_check.py` |

---

## 5. Data layer — exactly where every byte comes from

Two kinds of data, **never confused**:

- **TRAIN data** — pulled once into the cube, then never again.
- **LIVE data** — what the loggers write forever.

Several sources serve both jobs through *different endpoints*. Everything below is free.
`Access` states the exact requirement.

### 5.1 The master source table

| # | Source + endpoint | Gives us | Role | Access |
|---|---|---|---|---|
| **A1** | **Open-Meteo Archive** — `archive-api.open-meteo.com/v1/archive` | ERA5-Land hourly: precipitation, temp, RH, wind, surface pressure, CAPE, soil moisture; 1940–present; the 56-point NCR lattice | **TRAIN**: the answer key + observation features, 2018–2025 | none (no key) |
| **A2** | **Open-Meteo Historical Forecast** — `historical-forecast-api.open-meteo.com` | Past NWP runs **as issued** (ECMWF / GFS / ICON) with their issue time; 2021+ | **TRAIN**: leak-free NWP features | none |
| **A3** | **Open-Meteo Forecast** — `api.open-meteo.com/v1/forecast` | Live 0–72 h multi-model forecast, hourly | **LIVE**: logger every 60 min | none |
| **A4** | **GEE: `NASA/GPM_L3/IMERG_V07`** (+V08 when it lands) | Satellite rainfall, 0.1° / 30 min, 2000–present | **TRAIN**: nowcast frames + a second truth source. Export event windows + Jun–Sep 2018–2024 to NetCDF | GEE project (**active**) |
| **A5** | **GEE: `ESA/WorldCover/v200`, `JRC/GSW1_4`, `WorldPop/GP/100m/pop`, GHSL** | Landcover 10 m, permanent water, population 100 m, built-up surface | **TRAIN (static)**: impervious fraction, water mask, exposure | GEE (**active**) |
| **A6** | **GEE: `GLOBAL_FLOOD_DB/MODIS_EVENTS/V1`** | Historical flood extents 2000–2018 at 250 m | **TRAIN**: InundaNet labels (open tier) | GEE (**active**) |
| **A7** | **Copernicus GLO-30 DEM** — `s3://copernicus-dem-30m` (UNSIGNED boto3) | 30 m DEM. NCR = **2 tiles**: `N28 E076`, `N28 E077` | **TRAIN (static)**: DEM → HAND, slope, TWI, flow accumulation, curvature | none |
| **A8** | **glo-30-hand** — `s3://glo-30-hand.s3.us-west-2` (UNSIGNED) | Precomputed global HAND | Cross-check for our own `pysheds` HAND | none |
| **A9** | **OSM Overpass / `osmnx` + Geofabrik India extract** | `waterway=drain/canal/river`; hospitals, schools, pumps; road network | **TRAIN (static)**: drainage density, distance-to-drain; exposure assets; routing graph | none |
| **A10** | **DataMeet maps** — `raw.githubusercontent.com/datameet/maps` | Ward / district polygons | **TRAIN (static)**: aggregation geometry | none (tested) |
| **A11** | **`imdlib`** (IMD Pune gridded) | IMD 0.25° **daily** rainfall, 1901–2024 | **TRAIN**: daily cross-check of ERA5 / IMERG; extreme-day catalogue | none (pip package) |
| **A12** | **CHIRPS daily** — UCSB CHG HTTPS | 0.05° daily rainfall, 1981+ | **TRAIN**: climatology features | none |
| **A13** | **NOAA ISD / GSOD** — AWS S3 open bucket | Hourly synoptic observations: Safdarjung `421820`, Palam `421810` | **TRAIN**: sparse gauge supplement + demo credibility ("real stations in the cube") | none |
| **A14** | **IMD radar GIFs** — `mausam.imd.gov.in/Radar/{prod}_{site}.gif` | MAX-Z / SRI frames, ~10 min cadence, Delhi + Chennai | **LIVE**: logger. v0 shows frames in the UI; decoding is a later phase | none (poll politely) |
| **A15** | **IMD CAP alerts** — `cap-sources.s3.amazonaws.com/in-imd-en/rss.xml` | Official alert stream **with timestamps** | **LIVE**: benchmark logger → the lead-time proof (P-3) | none |
| **A16** | **ECMWF open data** (`ecmwf-opendata` package) | IFS / AIFS runs 4× daily: `tp`, `2t`, `10u/10v`, `msl`, `tcwv` | **LIVE**: logger; RainFuse live inputs | none |
| **A17** | **ADAPTERS (queued)** — Copernicus GFM 20 m flood, MOSDAC INSAT + GSMaP-ISRO, JAXA GSMaP, IMD AWS API (needs IP whitelisting), raw DWR volumes, NCUM/BharatFS | Agency-grade upgrades | Each approval = **one new ablation row**. **Nothing in v0 depends on any of them.** | signup / request |

### 5.2 Rejected sources — and the honest reason

Being able to say *"we evaluated it and excluded it, here is why"* scores more points than silently
not using something.

| Rejected | Reason |
|---|---|
| **Sentinel-2 for flood mapping** | Optical — **cloud-blind exactly when it floods**. Kept only as landcover context, which WorldCover already covers. Sentinel-1 (SAR) is the correct flood instrument and arrives via GFM / Earth Search as an upgrade. |
| **GPM DPR "satellite radar"** | Real radar, **wrong cadence**: a narrow swath twice a day cannot drive a 10-minute nowcast. |
| **Bhuvan bulk tile downloads** | Heavy and login-gated for bulk. Bhuvan WMS may appear later as an optional ISRO basemap toggle; it is **not a model input**. |
| **Kaggle / Colab GPUs** | Nothing in v0 needs a GPU. LightGBM on the NCR lattice trains in under a minute on CPU. **The bottleneck is data wrangling, not compute.** |
| **NASADEM** | No advantage over Copernicus GLO-30, which is already scripted. |

### 5.3 Extraction recipes — verified starting points

> **Rule 6 applies everywhere: fetch once, inspect the real response, *then* write the parser.**
> Never write a parser against an imagined schema.

```python
# --- A1: ERA5-Land hourly training target (no key) --------------------------
import openmeteo_requests, pandas as pd
om = openmeteo_requests.Client()
for lat in [28.35 + 0.1*k for k in range(7)]:          # 28.35 .. 28.95
    for lon in [76.90 + 0.1*k for k in range(8)]:      # 76.90 .. 77.60
        r = om.weather_api("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": lat, "longitude": lon,
            "start_date": "2018-06-01", "end_date": "2025-09-30",
            "hourly": ["precipitation","temperature_2m","relative_humidity_2m",
                       "wind_speed_10m","surface_pressure","cape",
                       "soil_moisture_0_to_7cm"],
            "timezone": "UTC"})[0]
        # -> cube/archive_{lat:.2f}_{lon:.2f}.parquet
```

```python
# --- A2: leak-free NWP training features (no key) ---------------------------
params = {"latitude": 28.65, "longitude": 77.22,
          "start_date": "2021-06-01", "end_date": "2025-09-30",
          "hourly": "precipitation",
          "models": ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]}
# store (issue_time, lead_h, lat, lon, p_ecmwf, p_gfs, p_icon)
# LAW: features at t0 may only use rows where issue_time <= t0
```

```python
# --- A4: IMERG 30-min frames via GEE (project ACTIVE) -----------------------
import ee; ee.Initialize(project="<our-project-id>")
ncr = ee.Geometry.Rectangle([76.85, 28.30, 77.65, 28.95])
col = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
         .filterDate("2024-06-26", "2024-06-29").select("precipitation"))
# export per-day stacks to Drive / NetCDF; ALSO pull Jun-Sep 2018-2024 overnight
# QUOTA NOTE: noncommercial projects sit on the GEE Community tier.
#   Use GEE for EXPORTS ONLY, never for heavy compute. Process locally.
#   Export small event windows first; bulk history overnight.
```

```python
# --- A7: DEM from public S3 (no credentials) --------------------------------
import boto3
from botocore import UNSIGNED
from botocore.config import Config
s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
for t in ["Copernicus_DSM_COG_10_N28_00_E076_00_DEM",
          "Copernicus_DSM_COG_10_N28_00_E077_00_DEM"]:
    s3.download_file("copernicus-dem-30m", f"{t}/{t}.tif", f"data/static/{t}.tif")

# pysheds pipeline: fill pits -> fill depressions -> resolve flats
#                   -> flow direction -> flow accumulation
# stream threshold: GRID-SEARCH [100, 250, 500, 1000, 2500] against OSM
#                   waterways, pick by F1  (Rule 7: fitted, not hardcoded)
# HAND = compute_hand(fdir, dem, acc > best_threshold)
# cross-check against s3://glo-30-hand
```

```python
# --- A9: drains + exposure assets (no key) ----------------------------------
import osmnx as ox
BBOX = (28.95, 28.30, 77.65, 76.85)          # north, south, east, west
drains = ox.features_from_bbox(*BBOX, {"waterway": ["drain","canal","river"]})
hosp   = ox.features_from_bbox(*BBOX, {"amenity": "hospital"})
G      = ox.graph_from_bbox(*BBOX, network_type="drive")
```

### 5.4 The event catalogue

Curated events are the spine of the demo. They are **hand-picked, never a free date picker** — every
click must demo well.

| Event | Why it matters |
|---|---|
| **28 Jun 2024** — **primary demo event** | 228 mm; the IGI airport terminal canopy collapsed. The single most recognisable Delhi rain disaster. |
| **8–13 Jul 2023** | Yamuna hit its all-time record of **208.66 m**; central Delhi flooded including ITO and Rajghat. |
| **19 Jul 2020** | Severe waterlogging event. |
| **1 Sep 2021** | Heavy monsoon event. |
| **IMD-gridded extreme days** | Additional extreme days pulled programmatically from A11 (`imdlib`) to enlarge the positive class. |

### 5.5 Live loggers — the irreplaceable asset

> **Nobody serves an archive of live feeds. Our loggers ARE the archive.** Every logged day is
> irreplaceable training data and an irreplaceable benchmark timestamp.

| Logger | Interval | Captures | Health rule |
|---|---|---|---|
| `radar_logger.py` (Delhi + Chennai) | 10 min | MAX-Z / SRI GIFs, sha256-deduplicated, UTC-stamped | gap > 30 min = **WARN** |
| `cap_logger.py` | 15 min | IMD CAP XML → parquet (`id, sent, area, event, severity`) | every alert is a benchmark timestamp |
| `openmeteo_logger.py` | 60 min | 56-point lattice, 3 models, 0–72 h, `issue_time = fetch_time` | gap > 2 h = **WARN** |
| `nwp_logger.py` (ECMWF) | 4× daily | `tp`, `2t`, `10u/10v`, `msl`, `tcwv` over the NCR box | missing run = **WARN** |
| `health_check.py` | on demand | Age of the newest file per feed | run morning and night; keep `caffeinate -is` on |

**Two-era data strategy.** The *satellite era* (2015–2025) trains the models now. The *radar era*
begins with our own GIF loggers (live since 28 Aug 2026) — by December we hold months of decoded
~1 km radar data that no competitor has. v0 **displays** radar frames; **decoding** is a later phase.

### 5.6 Verified source behaviour — what the probes actually found

> Charter rule **R6** in action. Every line here came from fetching the real thing and looking at it,
> not from documentation. **Two of these findings would have silently corrupted the models.**

#### Finding 1 — CAPE is absent from the archive endpoint

`cape` requested from `archive-api.open-meteo.com` returns **100% NULL** (64,704 / 64,704 rows,
dtype `object`) on *every* model — default, `era5`, and `era5_seamless`. CAPE is an ERA5
single-levels field, not an ERA5-Land one.

Written blind, RainCast would have trained on a dead column and nobody would have noticed.

**Resolution:** CAPE is sourced from **A2** (`historical-forecast-api`), which serves it fully
populated — 3990 J/kg during the 28 Jun 2024 window — along with two bonus instability features we
had not planned for, `convective_inhibition` and `lifted_index`. This is *architecturally better*:
A2 rows carry a real `issue_time`, so the instability features obey the no-look-ahead law (R4) for
free.

#### Finding 2 — ⚠️ ERA5 cannot be the sole truth layer for extremes

Measured on the flagship demo event (28 Jun 2024; Safdarjung recorded **228 mm**, the highest June
daily total since 1936, and the IGI terminal canopy collapsed):

| Source | Value near Safdarjung | Rank among 2024 NCR days |
|---|---:|---|
| **Reality** (IMD station, reported) | **228 mm** | the event of the year |
| **IMD gridded 0.25°** (A11, `imdlib`) | **150.7 mm** | **#1 wettest day of 2024** ✅ |
| **ERA5-Land** via Open-Meteo (A1) | **20.9 mm** | **not in the top 8** ❌ |

ERA5-Land is a ~9 km reanalysis, and reanalyses **smooth convective extremes**. Its *timing* is
correct — its peak lands at 22:00Z 27 Jun = 03:30 IST 28 Jun, matching the reported cloudburst — but
its *magnitude* is off by an order of magnitude and its maximum is misplaced to the south-east corner
of the box.

*(Note the timezone trap this exposes: the event is "28 June" in IST but straddles 27 June in UTC.
Charter rule **R8** — UTC internally, always — is what keeps this from silently halving the event.)*

**Consequences — load-bearing, not trivia:**

1. **ERA5 must not be the sole training target for heavy-rain exceedance.** A model trained only on
   ERA5 learns to predict *smoothed* rain and can never predict a cloudburst, because its answer key
   never contains one.
2. **IMD gridded becomes the truth layer for the daily exceedance heads** (RainFuse: 64.5 / 115.6 /
   204.5 mm). Those are IMD's **own official categories** — verifying them against IMD's **own
   observational product** is the most defensible choice available in front of IMD judges.
3. **ERA5 keeps its job:** hourly structure — lags, accumulations, antecedent indices, and the
   sub-daily dynamics RainCast needs. IMD gridded is daily only and cannot do that job.
4. **IMD gridded stops at 2024**, so the TEST split (2025) falls back to ERA5 + IMERG. State this.
5. **The disagreement is evidence for Proof P-1, not an embarrassment.** Two truth sources disagree
   in a measurable, explainable way. That *is* the argument for fusing source families instead of
   trusting one. Quantified, it belongs on the honesty slide — and it is a far stronger answer to
   *"why fusion?"* than any ablation row alone.

---

## 6. The fusion cube — one table everything trains on

### 6.1 Mental model

The cube is a spreadsheet. **Each row is one place at one moment.** The columns are everything every
source knows about that place-moment. One column is the answer.

"Fusion" simply means **all source families sit in the same row**, so the model can learn *which
columns to trust under which conditions* — and the ablation table (P-1) proves it actually did.

### 6.2 Specification

| Spec | Value |
|---|---|
| **Rain lattice** | 0.1°, **56 points** (8 lon × 7 lat) over the NCR box; hourly steps, UTC; monsoons Jun–Sep 2018–2025 |
| **Inundation grid** | **100 m** cells over the same box (~78 × 72 km ⇒ on the order of 5×10⁵ cells). Static features precomputed once; dynamic features joined per event-hour |
| **Store** | `cube/ncr_cube.zarr` (xarray). Static rasters as GeoTIFF in `data/static/`. Labels as GeoParquet in `data/labels/` |
| **Time convention** | **UTC everywhere, internally, always.** Convert to IST only at the presentation layer. |

### 6.3 The law (no look-ahead)

> Every forecast record keeps **both** `issue_time` and `valid_time`. The **only** read path is
> `cube.at(t0)`, which returns the latest data issued **≤ t0**.
> `eval/leakage_tests.py` shuffles future rows and **asserts the features are unchanged**. It runs
> in CI.

This is not bureaucratic. It is the difference between a model that works and a model that scores
well because it peeked. It is also the answer to the hardest judge question (§17).

### 6.4 Splits — by event and year, never random

| Split | Range |
|---|---|
| **TRAIN** | 2018–2023 (observations) / 2021–2023 (NWP features, since A2 starts 2021) |
| **VAL** | 2024 — **isotonic calibration is fitted here and only here** |
| **TEST** | 2025 — whole events held out |
| **InundaNet additionally** | 5 km **spatial-block CV** |

**Why never random:** adjacent grid cells and adjacent hours are strongly autocorrelated. A random
split puts near-duplicates of a test row into training, inflating every score. Splitting by event and
by year is the only honest option on this kind of data.

### 6.5 Cube checkpoint

```python
ds.sel(lat=28.65, lon=77.22).precip.plot()   # must show the 28 Jun 2024 spike
```
…and `eval/leakage_tests.py` must be green. Do not proceed past this until both hold.

---

## 7. The three models

All three are **LightGBM in v0**: fast on CPU, natively probabilistic, interpretable via SHAP,
trained in seconds.

**The model ladder** — climb it only in this order, and only on evidence:
`persistence → pySTEPS → gradient boosting (LightGBM) → deep networks (SmaAt-UNet / ConvLSTM)`.

> **Deep learning is deliberately out of scope for v0.** On this data volume and this timescale,
> boosted trees beat a half-trained U-Net, run in seconds on CPU, and explain themselves. Deep
> nowcasting nets are scheduled for the radar era, where they actually pay off.

### 7.1 RainCast-v0 — the 0–6 h nowcast

**Intuition:** persistence-with-correction. Rain that has been intensifying for two hours under high
CAPE usually keeps going; pySTEPS tells us where the existing rain is drifting; RainCast learns *when
to trust that extrapolation and when the atmosphere says otherwise.*

| Aspect | Specification |
|---|---|
| **Question** | `P(next-1h rain > 15 mm)` and `P(next-3h rain > 50 mm)` per lattice cell, at leads **1 / 2 / 3 / 6 h** |
| **Features** (all issued ≤ t0) | Observation lags 1/2/3/6 h + accumulations 3/6/24 h (ERA5 hourly + IMERG pooled); antecedent 3/7/15-day rain; latest ECMWF/GFS/ICON precipitation at valid time **+ their pairwise disagreement**; CAPE, RH, wind; HAND / slope / impervious (static); hour-of-day and day-of-year cyclical encodings |
| **Targets** | Binary exceedance heads. The **15 mm head is guaranteed**; positives are thin at 50 mm |
| **Baselines to beat** | (a) persistence `I(rain_now > thresh)`, (b) raw ECMWF at the same lead, (c) pySTEPS Lucas-Kanade extrapolation |
| **Model** | LightGBM, balanced class weights, ~500 trees, lr 0.05, column subsample 0.8; **separate model per lead** |
| **Metrics** | CSI, POD, FAR, Brier + reliability plot, **per lead and per threshold** |
| **CHECKPOINT** | `CSI(RainCast) > CSI(persistence)` **AND** `> CSI(raw ECMWF)` on the 2025 test monsoon. **If not met: add features — never add model complexity.** |
| **Outputs** | `models/raincast_v0.pkl`; per-event `rain_grid_{HHMM}.json` (§12.2); `reports/reliability_raincast.png`; pySTEPS frame PNGs for the animation |

### 7.2 RainFuse-v0 — the 6–72 h NWP correction

**Intuition:** *where physics is systematically wrong.* ECMWF, GFS and ICON each over- or
under-predict in **learnable situations**, and **their disagreement itself predicts uncertainty**.
RainFuse never replaces the physics — it **corrects and calibrates** it.

> This is the **most defensible ML claim in the entire pitch.** It is exactly what operational
> meteorology calls Model Output Statistics, done with modern tooling, and no meteorologist will
> argue with it.

| Aspect | Specification |
|---|---|
| **Question** | Calibrated `P(24-h rain > 64.5 / 115.6 / 204.5 mm)` per cell — **the official IMD heavy / very-heavy / extremely-heavy categories**. v0 ships the 24 h lead bucket; 6/12/48/72 h heads if time allows |
| **Features** | 3-model precipitation at lead (indexed by `issue_time`), **pairwise disagreement**, ERA5 climatological anomaly, last-24 h accumulation, terrain, monsoon-phase + time encodings, 3×3 NWP neighbourhood means |
| **Model + calibration** | LightGBM binary head per threshold + **q10 / q50 / q90 quantile heads**; **isotonic calibration fitted on VAL 2024** |
| **Metrics** | Brier, reliability, POD/FAR at the operating point; side-by-side map — **raw ECMWF vs RainFuse-corrected vs observed** for 28 Jun 2024 |
| **CHECKPOINT** | `Brier(RainFuse) < Brier(raw-ECMWF probability proxy)` and the reliability curve hugs the diagonal |
| **Outputs** | `models/rainfuse_v0.pkl`; the `forecast` block inside `rain_grid_*.json`; `reports/reliability_rainfuse.png` |

Using the **official IMD thresholds** (64.5 / 115.6 / 204.5 mm) rather than invented ones is a
deliberate, high-value choice: the output is directly comparable to IMD's own warning categories.

### 7.3 InundaNet-v0 — rain to water on the ground

**Intuition:** the interaction a threshold rule cannot express. **50 mm on a low-HAND,
high-impervious cell far from a drain with saturated soil floods; the same 50 mm two streets uphill
does not.** HAND alone is already a strong baseline — so even a modest ML lift over it is an honest,
visible, defensible win.

| Aspect | Specification |
|---|---|
| **Question** | `P(cell inundated)` at 100 m, aggregated to wards with **onset time** and **peak time** |
| **Static features** | HAND, TWI, slope, plan curvature, flow accumulation, distance-to-drain, drainage density, impervious fraction (WorldCover), built-up (GHSL), permanent-water occurrence (JRC GSW), historical waterlogging frequency |
| **Dynamic features** | Rain accumulations 1/3/6/24 h taken from **RainCast / RainFuse quantiles**; antecedent precipitation index 3/7/15 d; ERA5 soil moisture |
| **Labels (open tier)** | Geocoded **Delhi PWD + Traffic Police waterlogging points** (200 m buffer, onset from timestamps) + **DFO polygons** + **Global Flood Database** events intersecting NCR + timestamped news reports. **Negatives:** cells > 1 km from any positive within the same event window |
| **Model + validation** | LightGBM on cell-event rows; **5 km spatial-block CV**; AUC-PR, F1 at the operating point, reliability |
| **CHECKPOINT** | The 28 Jun 2024 `P(flood)` map ranks **Minto Bridge, ITO and Zakhira in the top quintile *without having been told about them***. Note: the purely static susceptibility map should already light them up **before** any ML — that is the sanity check |
| **Outputs** | `models/inundanet_v0.pkl`; `wards_{event}_{HHMM}.geojson`; per-ward SHAP **top-3 drivers rendered in plain words** |

**Flood ground truth is the hardest problem in this field, and we say so.** The mitigation is not to
pretend otherwise; it is spatial-block CV, honest AUC-PR reporting, and reported uncertainty.

### 7.4 Calibration and the operating point

- **Isotonic calibration per model head, fitted on VAL 2024 only.** Reliability diagrams are saved to
  `reports/` and rendered inside the product's Verification view. **Trust is a feature, not an
  appendix.**
- **Operating point:** the probability threshold that maximises CSI at a forecaster-acceptable FAR,
  chosen on validation. **The trade-off curve is displayed — never a single magic 0.5.**

### 7.5 The impact engine — deterministic, and we say so

```
flooded cells × exposure  →  people (WorldPop)
                             hospitals / schools (OSM)
                             road-km
                             pumps

ranking  = probability × exposure × criticality
onset    = first lead at which calibrated P crosses the operating point
```

> **The honest line for judges:** *"The flood probability is learned. The asset overlay is exact
> geometry — nobody wants a neural net guessing where hospitals are."*

**Bonus if time permits:** hospital-access routing — shortest path on the OSM road graph with
high-probability edges removed. Cheap to implement, spectacular on screen.

### 7.6 Source-dropout training

Models are trained with **random source dropout**, so that "radar out" and "satellite lagging" are
**real, valid model outputs** rather than crashes. The UI badges the degradation and the uncertainty
intervals widen accordingly. This can be toggled live in front of judges.

---

## 8. Evaluation and verification

`eval/` is a first-class deliverable, not an afterthought — it produces three of the four proofs.

| Script | Produces | Feeds |
|---|---|---|
| `eval/metrics.py` | CSI, POD, FAR, Brier, reliability points, AUC-PR, skill-vs-lead curves | `reports/metrics.json` |
| `eval/leakage_tests.py` | Shuffles future rows, asserts features unchanged. **Runs in CI.** | The honesty guarantee |
| `eval/ablation.py` | The ablation table: all-sources vs each single-source vs raw NWP | **Proof P-1** |
| `eval/verify_vs_cap.py` | Our threshold-crossing timestamp vs IMD's official CAP alert timestamp, at matched FAR | **Proof P-3** |
| `models/calibrate.py` | Isotonic maps + reliability diagrams | **Proof P-2** |

### 8.1 On "what is your accuracy?"

**Refuse to give a single number for rare events — it misleads.** Report:

- CSI / POD / FAR **per lead and per threshold**
- Brier **with** the reliability curve
- The operational headline: **minutes of lead time gained over IMD's own CAP alerts at matched
  false-alarm ratio**

All of it lives inside the product, on the Verification screen.

---

## 9. Repository layout

```
pravaah/
  configs/
    aoi_delhi_ncr.yaml        # THE region definition. Second region = a new file. (Proof P-4)
  scripts/                    # loggers + health_check (already live)
    radar_logger.py  cap_logger.py  openmeteo_logger.py
    nwp_logger.py    health_check.py
  ingest/                     # one adapter per source, shared record schema
  cube/
    grid.py                   # lattice + 100 m grid definitions
    build_cube.py             # assembles ncr_cube.zarr
    accessor.py               # THE latest-at-t0 read path — the only one
  features/
    static_hydro.py           # DEM -> HAND, TWI, slope, flow-acc, curvature
    dynamic.py                # lags, accumulations, antecedent indices
    nwp.py                    # multi-model features + disagreement
    exposure.py               # WorldPop x OSM x wards -> exposure table
  models/
    raincast_v0.py  rainfuse_v0.py  inundanet_v0.py
    calibrate.py    risk.py
    *.pkl                     # saved models — COMMITTED (a few MB)
  eval/
    metrics.py  leakage_tests.py  ablation.py  verify_vs_cap.py
  serve/
    main.py                   # FastAPI
    advisory.py               # LLM adapter + disk cache
    schemas.py                # pydantic models mirroring §12.2
  ui/                         # React app (Vite)
  ui-fallback/
    streamlit_app.py          # validation harness + emergency demo
  notebooks/                  # exploration only; logic is promoted into modules
  data/
    raw/     static/   labels/   # GITIGNORED (large)
    outputs/                     # COMMITTED — the demo runs on these files
  reports/                    # figures + metrics.json — COMMITTED
  docs/                       # charter, deck, demo script, access_log.md
  Makefile
  requirements.txt
  .env.example                # COMMITTED    (.env is gitignored)
  CLAUDE.md
```

### 9.1 What goes in git and what never does

| ✅ In git | ❌ Never in git |
|---|---|
| All code | `data/raw/` |
| `data/outputs/` (the demo runs on these) | `data/static/` |
| `models/*.pkl` (a few MB) | `*.zarr` |
| `reports/` (figures + `metrics.json`) | `.venv`, `node_modules` |
| `.env.example` | `.env`, API keys, GEE service-account JSON |

---

## 10. Backend — FastAPI over precomputed files

### 10.1 Philosophy

> **The models never run during the demo.** Every output for every curated event is precomputed into
> `data/outputs/` and committed. FastAPI is a **thin file reader**. Replay is just the clock.
> **If every API on earth is down on demo day, the demo does not notice.**

### 10.2 Endpoints

| Endpoint | Returns | Reads |
|---|---|---|
| `GET /api/events` | Curated event list + available timestamps | `outputs/index.json` |
| `GET /api/state?event&t` | City KPIs at clock `t` (rain now, P(3h>50), risk level, time-to-critical, people exposed) | `kpi_{t}.json` |
| `GET /api/wards?event&t` | Ward GeoJSON with `p_flood`, `onset`, `peak`, exposure, drivers, `risk_score` | `wards_{event}_{t}.geojson` |
| `GET /api/rain?event&t&lead&kind` | Rain probability grid (`kind` = `nowcast` \| `forecast`), with quantiles | `rain_grid_{event}_{t}.json` |
| `GET /api/frames?event&t` | pySTEPS / radar animation frame URLs | `outputs/{event}/frames/` |
| `GET /api/ward/{id}?event&t` | Single-ward detail: timeline, SHAP drivers, assets | slice of wards file + `timeline_{ward}.json` |
| `POST /api/advisory/{ward}?event&t` | Plain-language advisory (EN + HI). **Cache-first**: returns disk cache; regenerates only if online **and** cache miss | `advisory_{event}_{ward}_{t}.json` |
| `GET /api/verify/metrics` | Reliability points, skill-vs-lead, ablation rows, lead-time-vs-CAP table | `reports/metrics.json` |
| `GET /api/health` | Logger freshness + which sources feed the current view (the badges) | `health_check` output |
| `StaticFiles /` | The built React app (`vite build` → `dist/`) | **One origin, zero CORS, offline** |

### 10.3 Replay mechanics

The frontend clock picks `t`; **every endpoint filters to artefacts stamped ≤ t**. Because the
outputs were generated through the cube's latest-at-`t0` accessor, replay **automatically** shows
only what was knowable at that moment. The same honesty law, enforced end to end.

---

## 11. Frontend — the React command center

**React 18 + Vite + MapLibre GL + Recharts + Tailwind + react-router + zustand.**

**Not Next.js** — we need no SSR and no server components, and a plain Vite build produces a static
bundle FastAPI can serve from one origin, fully offline.

**Streamlit survives** as the ML validation harness *and* the emergency fallback demo. It reads the
**exact same output files**, so it is always in sync and always demo-ready.

### 11.1 Design language

| Token | Value |
|---|---|
| Background | `#0b1220` |
| Panel | `#111a2c` |
| Ink | `#e5edf7` |
| Accent — data | teal `#14b8a6` |
| Accent — warning | amber `#f59e0b` |
| Accent — critical | red `#ef4444` |
| Grid lines | `#1f2b40` |
| Font | **Inter, bundled locally** — no Google Fonts CDN (offline rule) |

- **The map needs no internet.** Every layer is our own GeoJSON on a dark canvas: ward polygons,
  drains, roads, water bodies, asset markers. **No external basemap tiles** = no tile-server
  dependency = airplane-mode safe — and it looks like a *control room*, not a consumer map. An online
  basemap toggle (CARTO dark) may exist but **defaults OFF**.
- **Motion with restraint.** Framer Motion for panel slides and the pulsing glow on critical wards
  (CSS keyframe `box-shadow` on the marker layer). Nothing animates during a data scrub except the
  map layers themselves.
- **Every number carries its uncertainty.** Probabilities show the calibrated value **plus a band**;
  onset times show the **90% interval**. Source badges (SAT / RADAR / NWP / STATIC, green-amber-red)
  sit in the top bar on **every** view.

### 11.2 The six views

| View / route | Purpose + key components | Endpoints |
|---|---|---|
| **1 · Command Center** `/command` | The one screen a control room keeps open. **Top bar**: region, Live\|Replay toggle, clock, source badges. **KPI strip** (5 cards): rain now, P(3h>50 mm), city flood risk, time-to-critical, people exposed. **Centre**: ward choropleth (layer switch: rain prob \| inundation \| risk \| exposure) + asset markers with glow on critical + lead slider. **Right rail**: ranked wards (score, onset, top driver) + an "Issue CAP" button → mock CAP card modal. **Bottom**: selected-ward strip + advisory button | `/api/state`, `/api/wards`, `/api/rain`, `/api/health` |
| **2 · Nowcast** `/nowcast` | 0–6 h. Animated probability field (pySTEPS + RainCast frames, play/pause), lead stepper 0.5–6 h, threshold toggle 15\|50 mm, **skill-vs-lead curve showing the honest decay after ~2 h**, radar GIF panel with live frames from our logger | `/api/rain?kind=nowcast`, `/api/frames` |
| **3 · Forecast** `/forecast` | 6–72 h. Exceedance choropleth at 64.5\|115.6\|204.5 mm with a 6-h stepper; side-by-side small multiples: **raw ECMWF vs RainFuse-corrected vs observed**; quantile fan chart q10/q50/q90 for a clicked cell; model-agreement mini-map | `/api/rain?kind=forecast` |
| **4 · Inundation + Impact** `/inundation` | **The USP view.** 100 m flood-probability raster + ward aggregation. Click a ward → detail panel: probability timeline with the operating point marked, onset/peak + 90% interval, **SHAP top-3 drivers as plain-word bars**, affected-assets table (people, hospitals, schools, road-km, pumps), affected-radius glow around critical assets, AI-advisory button | `/api/wards`, `/api/ward/{id}`, `/api/advisory` |
| **5 · Replay** `/replay` | Event dropdown (28 Jun 2024 default, Jul 2023, Jul 2020, Sep 2021 — **curated, never a free date picker**). Clock runs at 10× with play/pause/speed. All panels show only data issued ≤ t. At the end: observed-outcome overlay + a "what we said vs what happened" strip | all endpoints with `event` + `t` |
| **6 · Verification** `/verify` | **Aimed squarely at IMD judges.** Reliability diagrams per model; skill-vs-lead curves; **the ablation table**; lead-time-vs-CAP table; split-methodology note. A static render of `reports/` — zero runtime risk | `/api/verify/metrics` |
| **AI Advisory drawer** (global) | Slides in from the right on any view. Shows the cached bilingual advisory for the selected ward + a "regenerate" button that only works online. Footer label: **"AI-generated narration of model outputs — the models forecast, the AI explains."** | `/api/advisory/{ward}` |

### 11.3 Component build order

```
AppShell (sidebar, topbar, badges)
  └─ MapCanvas (MapLibre wrapper + GeoJSON layer registry)
       └─ ChoroplethLayer, AssetMarkers, GlowPulse
  └─ LeadSlider + ReplayClock   (zustand store: {event, t, lead, layer})
  └─ KpiCard, RankedList, WardDetailPanel, DriverBars,
     TimelineChart (Recharts), FanChart, SmallMultiples
  └─ CapModal, AdvisoryDrawer, VerifyCharts
```

**Build in this order, and every component renders from fake files first.**

### 11.4 Offline packaging — a hard gate, not an optimisation

- `vite build` → `frontend/dist`; FastAPI mounts it via `StaticFiles` at `/`. One origin, no CORS,
  one command: `uvicorn serve.main:app`.
- All fonts, map-style JSON and GeoJSON are **local assets**. The **only** network calls the app ever
  makes are to `localhost`.
- **Acceptance test: wifi OFF, cold start, full 3-minute demo, zero console errors.** Not optional.

---

## 12. Contracts

### 12.1 Why contracts exist

**The frozen file contracts are the reason parallel work is possible at all.** Fake files matching
these schemas are written *first*; the entire app is built against fakes; later the real files
replace the fakes and **nothing breaks**.

Any change to a schema requires an announcement and a **version bump in `outputs/index.json`**.

### 12.2 The frozen file contracts

**`data/outputs/index.json`**
```json
{"events": [{"id": "2024-06-28",
             "name": "Delhi cloudburst 28 Jun 2024",
             "timestamps": ["0400", "0430", "..."],
             "wards": 250}],
 "schema": 3}
```

**`data/outputs/{event}/wards_{HHMM}.geojson`** — one FeatureCollection
```json
"properties": {
  "ward_id": "W047",
  "name": "Minto Bridge",
  "p_flood": 0.78,
  "onset": "06:30",
  "peak": "07:15",
  "ci90": ["06:40", "07:50"],
  "people": 12400, "hospitals": 2, "schools": 4,
  "road_km": 3.1, "pumps": 1,
  "drivers": [["low HAND", 0.31], ["impervious", 0.18], ["antecedent rain", 0.12]],
  "risk_score": 0.82,
  "risk_band": "critical"
}
```
`risk_band` ∈ `low` | `watch` | `high` | `critical`

**`data/outputs/{event}/rain_grid_{HHMM}.json`**
```json
{"kind": "nowcast",
 "lead_h": 3,
 "cells": [{"lat": 28.65, "lon": 77.20,
            "p15": 0.62, "p50": 0.31,
            "q10": 4.0, "q50": 18.0, "q90": 41.0}],
 "forecast": {"lead_h": 24,
              "thresholds": {"64.5": 0.41, "115.6": 0.12, "204.5": 0.01}}}
```

**`data/outputs/{event}/kpi_{HHMM}.json`**
```json
{"rain_now_mm_h": 18.2,
 "p3h50": 0.71,
 "city_risk": "HIGH",
 "time_to_critical_min": 130,
 "people_exposed": 46200,
 "badges": {"sat": "ok", "radar": "ok", "stations": "degraded", "nwp": "ok"}}
```

**`data/outputs/{event}/advisory_{ward}_{HHMM}.json`**
```json
{"advisory_en": "...",
 "advisory_hi": "...",
 "actions": ["...", "...", "..."],
 "generated": "2026-08-31T18:40Z",
 "cached": true}
```

**`reports/metrics.json`** — reliability points, skill-vs-lead curves, ablation rows, lead-time
table. Consumed by `/verify`.

---

## 13. The AI advisory layer

**Purpose:** close the last gap in the problem statement — *a millimetre number does not say which
hospital access road to protect.* The LLM turns model JSON into a plain-language, **bilingual** ward
advisory that a duty officer can act on at 4 a.m.

### 13.1 The iron rule

> **The LLM never predicts. It narrates numbers the models already computed.**
> Every figure in its output must exist in the JSON we passed it.
> The UI labels it *"AI-generated narration of model outputs"*.
> **The models forecast; the AI explains.**

### 13.2 Specification

- **Provider:** Claude API or Gemini API — whichever key is available. The adapter is ~15 lines and
  model choice does not matter at this quality bar.
- **Input contract:**
  `{ward_name, p_flood, onset, peak, ci90, people, hospitals[], schools, road_km, pumps, drivers[3], event_context}`
- **Output contract:** `{advisory_en, advisory_hi, actions[3]}` — three concrete actions, **each tied
  to an asset present in the input**.
- **Prompt skeleton:**
  > *"You are drafting an operational flood advisory for a Delhi ward officer. Use ONLY the numbers in
  > the JSON. Do not invent figures, places or times. 120 words max per language. State: risk +
  > timing, who/what is exposed, top drivers in plain words, three concrete actions."*
- **Caching:** advisories are **pre-generated for every (event, critical ward, timestamp) tuple**
  before the demo and committed to `data/outputs/`. The demo serves cache. "Regenerate" exists only
  to prove it is live-capable when online.
- **Failure mode:** no key / offline / rate-limited → serve cache. Cache miss → render the structured
  numbers with a *"narration unavailable"* note. **The demo never blocks on an LLM.**

### 13.1 Grounded chat (`serve/chat.py`) — shipped

`POST /api/chat` answers questions about what is on screen. **Model:
`gemini-3.5-flash-lite`, chosen on rate limits, not quality.** The free tier's
binding constraint is requests-per-day and it varies by an order of magnitude
inside one family — flash 5 RPM / **20 RPD**, flash-lite 15 RPM / **500 RPD**.
Twenty requests would not survive a single demo. Lite is also 3.6× faster on
this task (1.3 s vs 4.7 s) because the larger models spend ~360 *thinking*
tokens per call, which was truncating replies.

Two facts worth keeping:

- **Gemini's "Live API" is the wrong surface for this.** `bidiGenerateContent`
  is bidirectional streaming for **voice and video**. A text Q&A over a fixed
  JSON context wants `generateContent`; using Live would add websockets, audio
  framing and turn management to a request/response question.
- **A prompt instruction is not a control.** Every number in a reply is checked
  against the context and the reply is **rejected**, not caveated, if it invents
  one. With no key or any API failure the endpoint returns a deterministic
  answer built from the same context, so it can neither fabricate nor fail.

### 13.2 The sandbox (`serve/sandbox.py`) — and the model's own evidence boundary

`POST /api/sandbox` runs **InundaNet live on 148,776 real 100 m cells** against
rainfall the user invents (0.10 s warm). Synthetic: the four rain inputs. Real:
the terrain features, the grid, the ward geometry, the exposure counts and the
trained model. Every response carries `is_forecast: false`.

This is the one place the "no lightgbm in `serve/`" rule is broken, and the
exception is scoped rather than waived: lazy import, shipped artefact, no
training path, and every other route survives its absence.

**Building it exposed a real limit, which we now ship rather than hide.** The
trained booster's highest split on `rain_sum` is **25.30 mm**, so above that it
is *mathematically constant* in event rainfall — 40 mm, 120 mm and 300 mm return
byte-identical answers. A 0–300 mm slider would have been a control that does
nothing over 90 % of its travel. The endpoint reads that boundary out of the
artefact (`evidence.limits_mm`) and serves a response curve so the flattening is
**drawn, not asserted**. Within the evidenced range it moves properly: 8 → 11 →
17 → 23 high-risk wards across the presets.

> **Why quantile mapping cannot fix this — and where it does belong.**
> Quantile mapping is a strictly monotone transform, and a decision tree splits
> on **order**. Mapping InundaNet's rain *inputs* therefore yields the identical
> tree with rescaled thresholds: it relabels the axis and cannot widen the
> response. The bias correction belongs to **RainCast**, where the compressed
> quantity is the **target** — ERA5 gave 20.9 mm on 28 Jun 2024 where IMD's
> gauge grid said 150.7, so the model has never seen a cloudburst as a positive,
> which is why the 15 mm/h head had 63 test positives and was dropped.

Units are a trap here and are stated on every response: `rain_sum` is a **6-hour
ERA5 accumulation**, *not* IMD's 24-hour 64.5 / 115.6 / 204.5 mm categories.
Presets built from the latter all saturate and return one answer.

---

## 14. Non-negotiable engineering rules

These rules are the difference between a demo that survives judge scrutiny and one that does not.

| # | Rule | Why |
|---|---|---|
| **R1** | **The demo never touches the internet.** Everything is precomputed and committed. | Venue wifi is not a dependency you get to have. |
| **R2** | **One shared record shape for every source adapter.** `(source, variable, valid_time, issue_time, geometry, value, quality)` | It is what makes gated-source upgrades free. |
| **R3** | **"Run it, show it, then say done."** Every claim of completion comes with real output — a plot, a metric line, a screenshot. | Prevents the classic hackathon collapse at integration time. |
| **R4** | **No look-ahead.** Both timestamps on every forecast record; exactly one read path (`cube.at(t0)`); an automated leakage test in CI. | §6.3. This is the single most important technical rule. |
| **R5** | **Splits by event and by year — never random.** | Random splits on autocorrelated grids inflate scores. |
| **R6** | **Fetch once, inspect the real response, *then* write the parser.** | Never write a parser against an imagined schema. Half of all data-layer time is lost this way. |
| **R7** | **No hardcoded constants.** Thresholds, the stream network threshold, risk weights — **every constant traces to a script that fitted it**. Stream threshold is grid-searched against OSM waterways by F1; the operating point is chosen on validation; risk weights are documented. | "Fitted, not hardcoded" is a direct answer to a judge question (§17). |
| **R8** | **UTC internally, always.** Convert to IST only at the presentation layer. | Timezone bugs in a time-series pipeline are silent and fatal. |
| **R9** | **Learned vs deterministic is stated explicitly.** Learned: rain probabilities, NWP correction, flood probability, SHAP drivers. Deterministic and proudly so: exposure overlay, CAP formatting, routing. | Overclaiming is the fastest way to lose credibility. |
| **R10** | **An atomic swap is only atomic for the data you own.** Before replacing a directory or file that a *sibling* writer also touches, carry that writer's contents forward explicitly — and copy rather than move, so a failure mid-swap leaves the previous good state intact. | Cost us the same bug twice: `precompute` deleting `live` from `index.json`, then `live_update`'s directory rename destroying the radar frames `publish_radar` had written. Both were silent; both looked like "the data was never produced". |
| **R11** | **A model is constant above its highest split on a feature.** Before shipping any control that varies a model input, read the trained artefact's split thresholds and expose that boundary. Never ship a slider whose travel exceeds the model's evidence without labelling where the evidence ends. | The sandbox's `rain_sum` slider was dead above 25.3 mm. Showing the wall reads as rigour; being caught behind it reads as overclaiming. |

---

## 15. Build order and phase gates

Phases are ordered by **dependency and by risk**, not by preference. **No phase opens until the
previous checkpoint is green.**

| Phase | Deliverable | Gate condition |
|---|---|---|
| **S0 · Environment** | Python 3.11 venv with the full stack; GEE authenticated; repo skeleton; contracts + **fake output files** written | `make fakes && uvicorn serve.main:app` renders something on fake data |
| **S1 · Static hydrology** | DEM tiles → pysheds pipeline → HAND, TWI, slope, flow accumulation, curvature; OSM drains + assets; ward polygons; exposure table | The **static susceptibility map alone** lights up Minto Bridge / ITO / Zakhira. *This is the highest-value early win: it is a real result with zero ML risk.* |
| **S2 · The cube** | A1 + A2 + A4 pulls → `ncr_cube.zarr`; the latest-at-`t0` accessor; the leakage test | 28 Jun 2024 spike visible in `ds.sel(...).precip.plot()`; **leakage test green** |
| **S3 · RainCast-v0** | Nowcast model + persistence / pySTEPS / raw-ECMWF baselines | CSI beats **all three** baselines on test |
| **S4 · InundaNet-v0** | Labels geocoded; spatial-block CV; SHAP drivers; `wards_*.geojson` | Known hotspots in the top quintile **unprompted**; AUC-PR reported honestly |
| **S5 · RainFuse-v0** | NWP correction + quantile heads + isotonic calibration | Brier beats raw ECMWF; reliability hugs the diagonal |
| **S6 · Precompute + backend** | All outputs written for the curated events; FastAPI serving real files; advisories cached | Replay of 28 Jun 2024 runs end to end on real numbers |
| **S7 · Frontend + offline gate** | Six views on real data; `vite build` served by `StaticFiles` | **Wifi OFF, cold start, full 3-minute run, zero console errors** |
| **S8 · Verification** | `metrics.json` complete: ablation rows, reliability, lead-time vs CAP | All four proofs visible inside the product |
| **S9+ · After the round** | Radar GIF decoding, deep nowcast nets (SmaAt-UNet / ConvLSTM), conformal prediction intervals, Copernicus GFM labels, agency adapters, second region | — |

### 15.1 The pre-agreed cut order

**Decided in advance, never negotiated under pressure:**

```
drop second event
  → drop forecast small-multiples
    → drop the routing bonus
      → drop RainFuse extra leads
        → present the Streamlit fallback
```

**Never cut: InundaNet, Replay, Command Center. Those three *are* the pitch.**

---

## 16. Risk register

| Risk | Mitigation |
|---|---|
| **Loggers die silently** | `health_check.py` morning and night; `caffeinate -is`; GitHub Actions mirror. A short gap dents the radar-era story, not the v0 demo. |
| **GEE quota / export slowness (Community tier)** | Export small event windows first (28 Jun 2024), bulk history overnight. **ERA5 via Open-Meteo already covers the training target if IMERG exports lag** — IMERG is an enhancement, not a dependency. |
| **Too few flood positives after geocoding** | Widen the buffer to 300 m, add the 2023 / 2021 events, lean on GFD polygons; report AUC-PR honestly. **The static susceptibility map still demos regardless.** |
| **React integration slips** | Pre-agreed cut order (§15.1); the **Streamlit fallback reads identical files** and is always demo-ready. The pitch survives on the fallback. |
| **No internet / projector-only laptop at the venue** | The airplane-mode gate on two machines; a **screen recording of the full demo** embedded in the deck as the final fallback. |
| **A judge asks for a live prediction on today** | The Live tab shows today's logged feeds + ranked wards from this morning's precompute run, framed honestly as *"live view, refreshed this morning"*. |
| **Overclaiming under pressure** | Drill the §17 answers. **The honesty slide (stated limits) is IN the deck**, so nothing is hidden waiting to be discovered. |
| **Geospatial dependency hell** (`pysheds` / `rasterio` / `geopandas` / `pysteps` on Apple Silicon) | Pin the environment early; prefer conda-forge or `uv` if pip wheels fight. **Do this in S0, never mid-build.** |

---

## 17. Judge Q&A bank — the hard questions

| Question | The answer |
|---|---|
| **How is this different from iFLOWS / CFLOWS?** | Those are excellent NWP + gauge + 2D-hydrodynamic systems for two cities, each needing a bathymetry survey. PRAVAAH adds the **0–6 h learned nowcast they lack**, fuses four source families with calibrated probabilities, **learns inundation from labels instead of surveys**, and stands up a new district from a config file. Delhi has no iFLOWS; we built its equivalent from open data and made it portable. |
| **You don't have raw radar. Isn't that fatal?** | Correct, and it is stated on our own slide. The prototype **logs and displays IMD's public radar imagery every 10 minutes**, and the raw-volume adapter is already written — it slots in the day access is granted, adding one ablation row. Meanwhile the fusion of satellite, stations and NWP carries the skill, and results are labelled by era throughout. |
| **How do we know there's no data leakage?** | Every forecast row keeps `issue_time`; the cube has **exactly one read path**, returning the latest data issued at or before `t0`; an automated test shuffles future rows and asserts features are unchanged; splits are by event and by year, never random. Random splits on autocorrelated grids inflate scores — ours don't. |
| **What's your accuracy?** | We refuse a single number on rare events — it misleads. We report **CSI / POD / FAR per lead and threshold**, **Brier with reliability curves**, and the operational headline: **minutes of lead time gained over IMD's own CAP alerts at matched false-alarm ratio**. All of it is on the Verification screen. |
| **Why should we trust an 80% probability?** | Because it is **isotonic-calibrated on a held-out year** and the reliability diagram is **one click away inside the product**. When PRAVAAH says 80%, historically it happened about 80% of the time. |
| **Only one city?** | **Rainfall runs nationwide today** — it is grid-based. Inundation is demonstrated for Delhi because it needs per-city terrain and labels, but that is a **one-time automated geoprocessing job from a YAML config — hours, not years-plus-a-survey**. The config for a second region is in the repo. |
| **Is the AI doing the forecasting?** | **No.** Three LightGBM models and pySTEPS do the forecasting from the fused cube. The LLM only **narrates** the computed numbers into plain-language advisories — it is forbidden to invent figures, every advisory is generated from a JSON of model outputs, and each is cached and labelled. |
| **Which parts are ML and which are rules?** | **Learned:** rain probabilities, NWP correction, flood probability, SHAP drivers. **Deterministic and proudly so:** the exposure overlay (nobody wants a model guessing where hospitals are), CAP formatting, routing. **Fitted-not-hardcoded:** thresholds, the stream network, risk weights — every constant traces to a script in the repo. |
| **What if a source fails during operation?** | **Source-dropout training** means radar-out and satellite-lagged modes are **real model outputs, not crashes**. The UI badges the degradation and the intervals widen. We can toggle it live. |
| **Flood ground truth is weak. Will you admit it?** | Yes — **urban flood labels are the hardest problem in this field.** We fuse PWD / traffic waterlogging records, DFO and the Global Flood Database now; the Copernicus GFM Sentinel-1 archive joins on account approval. **Spatial-block CV and reported uncertainty keep us honest about it.** |
| **Why LightGBM and not deep learning?** | **Model ladder by evidence:** persistence → pySTEPS → gradient boosting → deep nets. On these data volumes and this timeline, boosted trees beat a half-trained U-Net, run in seconds on CPU, and **explain themselves via SHAP**. SmaAt-UNet / ConvLSTM are scheduled for the radar era, where they pay off. |
| **Scale to all-India in production?** | Grid-based inference is **seconds per district on CPU**; heavy geoprocessing happens **once per district**; loggers are horizontal. The national rainfall layer already runs; districts onboard as configs. |
| **Why did you not use MOSDAC / IMD APIs?** | **We use every IMD product that is public today** — CAP alerts, radar imagery, gridded rainfall — and our MOSDAC / GFM / Earthdata accounts are in approval. The architecture treats every gated feed as an **adapter**, so approvals upgrade the system without rework. **That is a design choice, not a workaround.** |
| **What would you do with agency access?** | Three things, in order: **raw DWR volumes** to replace GIF decoding (better 0–2 h skill), the **AWS gauge archive** to recalibrate all truth layers, and **NCUM / BharatFS** as a fourth NWP column. Each lands as one adapter + one ablation row — **measurable, not rhetorical**. |

---

## 18. The pitch — deck and demo

### 18.1 Eight slides

| # | Slide | Content |
|---|---|---|
| 1 | **The gap** | NWP takes hours; warnings are district-scale; rain is not flood; data is siloed. iFLOWS / CFLOWS: two cities, years each, bathymetry surveys. Delhi — 30 million people — has none. One map, one sentence. |
| 2 | **PRAVAAH in one picture** | The architecture diagram. Say: *five open source families, one honesty law (`issue_time`), three models, one command center.* |
| 3 | **Live proof** | Screenshot of the Command Center on **today's logged data** with source badges — proves it is **operational, not a mockup**. |
| 4 | **Replay 28 Jun 2024** | *"At 04:00 PRAVAAH said Minto Bridge, 78%, by 06:30"* — then the observed overlay. **The money slide**; mostly a screen-recorded backup of the live demo. |
| 5 | **The four proofs** | Ablation rows, reliability diagram, lead-time vs IMD CAP timestamps, config-only portability. Four small panels, real numbers, **no adjectives**. |
| 6 | **Rain to people** | InundaNet + impact engine: the HAND stack, learned labels, exposure join, onset time, the AI advisory card (EN + HI). |
| 7 | **Honesty + roadmap** | Stated limits: GIF-decoded radar not raw volumes; SAR blind in dense cores; open labels first. Then the roadmap: radar era, GFM, agency adapters, second region, deep nowcast. |
| 8 | **The ask** | A pilot with one Flood Met Office + raw radar access for Delhi. Team + QR to the repo. |

### 18.2 The 180-second click path

| Time | Action |
|---|---|
| **0:00–0:20** | Command Center, **Live** mode: *"this is running on data our loggers pulled this morning; the badges show which sources are feeding it."* |
| **0:20–1:30** | **Replay 28 Jun 2024 at 10×** from 04:00: the nowcast blob grows, the ward list re-ranks, **Minto Bridge goes critical at 78%, onset 06:30**. Pause. *"Everything on screen uses only data issued before this clock."* |
| **1:30–2:10** | Click Minto Bridge: timeline, drivers in plain words, assets, **AI advisory in English and Hindi**. *"The models forecast; the AI explains."* |
| **2:10–2:40** | **Verification view**: reliability + lead-time vs CAP. *"When we say 80%, it floods about 80% of the time; we beat the official alert by N minutes on this event."* |
| **2:40–3:00** | The ask + the portability line: *"new district = one config file."* |

---

## 19. Environment bring-up

```bash
# Python (ML + backend)
python3.11 -m venv .venv && source .venv/bin/activate
pip install xarray zarr rioxarray rasterio pysheds osmnx geopandas shapely \
    lightgbm scikit-learn pysteps matplotlib pandas numpy pyarrow \
    fastapi uvicorn boto3 requests openmeteo-requests requests-cache \
    retry-requests imdlib earthengine-api streamlit streamlit-folium folium \
    python-dotenv anthropic google-generativeai shap

earthengine authenticate        # once per machine; the GEE project is ACTIVE
```

```bash
# Frontend
npm create vite@latest ui -- --template react
cd ui && npm i maplibre-gl recharts zustand react-router-dom clsx framer-motion \
    tailwindcss @tailwindcss/vite lucide-react
```

```bash
# Keys:  .env  ->  ANTHROPIC_API_KEY=...   (or GEMINI_API_KEY=...)
#        .env is gitignored; .env.example is committed
```

```bash
# Sanity check
make fakes && uvicorn serve.main:app --reload
#   -> http://localhost:8000 renders the app on fake data
```

> **Note:** Python **3.11** specifically. The geospatial stack (`pysheds`, `rasterio`, `geopandas`,
> `pysteps`) has the best wheel coverage there. Do this in S0 — never discover a build failure
> mid-pipeline.

---

## 20. Key links

| Resource | URL |
|---|---|
| Open-Meteo Archive / Historical-Forecast / Forecast | `archive-api.open-meteo.com` · `historical-forecast-api.open-meteo.com` · `api.open-meteo.com` |
| GEE code editor + collections | `code.earthengine.google.com` — `NASA/GPM_L3/IMERG_V07`, `ESA/WorldCover/v200`, `GLOBAL_FLOOD_DB/MODIS_EVENTS/V1`, `WorldPop/GP/100m/pop`, `JRC/GSW1_4` |
| Copernicus DEM S3 / HAND S3 | `s3://copernicus-dem-30m` · `s3://glo-30-hand` (both UNSIGNED) |
| IMD radar / CAP | `mausam.imd.gov.in/responsive/radar.php` · `cap-sources.s3.amazonaws.com/in-imd-en/rss.xml` |
| IMD gridded / imdlib | `imdpune.gov.in` Griddata · `pypi.org/project/imdlib` |
| NOAA ISD on AWS | `registry.opendata.aws/noaa-isd` |
| OSM Overpass / Geofabrik / DataMeet | `overpass-api.de` · `download.geofabrik.de/asia/india` · `github.com/datameet/maps` |
| DFO / CWC / GFM / Earth Search | `floodobservatory.colorado.edu` · `ffs.india-water.gov.in` · `global-flood.emergency.copernicus.eu` · `earth-search.aws.element84.com/v1` |
| pySTEPS / LightGBM / pysheds | `pysteps.github.io` · `lightgbm.readthedocs.io` · `github.com/mdbartos/pysheds` |

---

## 21. Final word

> **No step opens until the previous checkpoint is green.**
> The minimum that wins is a **three-minute demo, in airplane mode, on real numbers**, with all four
> proofs visible inside the product.
> Everything in this document serves that demo or one of those four proofs.
> **Build exactly this. Upgrade afterwards.**

---

*Document status: master reference, derived from Build Charter v3.0. Team-agnostic by design —
ownership and scheduling live outside this file.*
