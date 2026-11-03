 # PRAVAAH — EXPLAINED

**The ground-up understanding + judge-defence document.**

> This file exists so that you can answer *any* question, at *any* depth, about
> this project. It starts from "what is a weather satellite" and ends at
> "why isotonic regression and not Platt scaling".
>
> **How it is written:** every topic goes *plain English first, technical second.*
> Read the plain part to build the picture. Read the technical part to defend it.
> Boxes marked **🎤 IF A JUDGE ASKS** give you the words to say out loud.
>
> **This is a living document.** As you ask more questions, new sections get
> inserted in the right place in the Contents below — the numbering is designed
> to allow insertion without renumbering everything.

**Status of this document:** covers Parts 1–9. Last synced against the repo at
commit `8aeed38` (live pipeline landed, all three models wired).

---

# CONTENTS

### PART 1 — FUNDAMENTALS: how humanity knows what the weather will do
- 1.1 The four ways to observe the sky (and why you need all four)
- 1.2 Rain gauges — the oldest and still the most trusted
- 1.3 Weather radar — and what the Doppler effect actually is
- 1.4 Weather satellites — GEO vs LEO, and how a satellite "sees" rain
- 1.5 NWP — what a physics simulation of the atmosphere really is
- 1.6 Reanalysis (ERA5) — the answer key, and why it is not a forecast
- 1.7 The forecast timeline — nowcast vs forecast, and the 0–6 hour hole
- 1.8 Rain ≠ flood — the hydrology you need in your head
- 1.9 🎤 Judge questions on fundamentals

### PART 2 — THE PROBLEM STATEMENT AND OUR ANSWER
- 2.1 SIH26071, stated exactly
- 2.2 The four gaps we exist to close
- 2.3 What PRAVAAH actually is, in one paragraph
- 2.4 The four proofs — our definition of "done"
- 2.5 Why Delhi NCR is the pilot
- 2.6 🎤 Judge questions on scope and framing

### PART 3 — THE DATA: every byte, and where it came from
- 3.1 The master source table (exact names, exact endpoints)
- 3.2 What each source physically is
- 3.3 What we evaluated and rejected — and the honest reason
- 3.4 The 228 mm story — when three truth sources disagree
- 3.5 TRAIN data vs LIVE data — two lanes that never touch
- 3.6 🎤 Judge questions on data

### PART 4 — GEOGRAPHY: degrees, grids, lattices and wards
- 4.1 What a "degree" means in kilometres
- 4.2 The 0.1° rain lattice — why 56 points
- 4.3 The 100 m inundation grid — why 561,600 cells
- 4.4 Wards — the unit a control room actually acts on
- 4.5 **THE KEY QUESTION: how do 56 rain values become 289 ward predictions?**
- 4.6 CRS and EPSG codes — why there are two of them
- 4.7 🎤 Judge questions on spatial resolution

### PART 5 — THE FUSION CUBE
- 5.1 What it is — with a real worked example row
- 5.2 `issue_time` vs `valid_time` — the single most important idea
- 5.3 The no-look-ahead law, and the bug it caught
- 5.4 The splits — why by year and never random
- 5.5 The three derived tables
- 5.6 🎤 Judge questions on leakage

### PART 6 — THE MODELS
- 6.1 Data provenance — exactly what feeds each model
- 6.2 What LightGBM actually is (decision tree → boosting → the maths)
- 6.3 Why LightGBM and not deep learning / XGBoost / anything else
- 6.4 RainCast-v0 — the 0–6 h nowcast
- 6.5 RainFuse-v0 — the 6–72 h NWP correction
- 6.6 InundaNet-v0 — rain to water on the ground
- 6.7 Calibration — what isotonic regression does and why
- 6.8 Every metric, explained (CSI, POD, FAR, Brier, AUC-PR, ROC-AUC)
- 6.9 SHAP — how "78%" becomes "because it is next to an underpass"
- 6.10 🎤 Judge questions on modelling

### PART 7 — INFERENCE: how a prediction reaches the screen
- 7.1 Training vs inference — two different things people confuse
- 7.2 The REPLAY path — precomputed historical events
- 7.3 The LIVE path — what happens when you press refresh
- 7.4 The backend — FastAPI as a file reader
- 7.5 The frontend — six views and what each proves
- 7.6 🎤 Judge questions on the product

### PART 8 — SCALE, PORTABILITY AND ECONOMICS
- 8.1 The honest answer: which model is the bottleneck
- 8.2 RainFuse — already multi-state today
- 8.3 RainCast — national is possible, with one real caveat
- 8.4 InundaNet — labels are the blocker, not compute
- 8.5 How we break the label constraint
- 8.6 What it would actually cost to run nationally
- 8.7 🎤 Judge questions on scaling and money

### PART 9 — HONEST LIMITS AND THE HARDEST QUESTIONS
- 9.1 The stated-limits list (memorise this)
- 9.2 The negative results we kept
- 9.3 The full judge Q&A bank
- 9.4 What to say when you do not know

---
---

# PART 1 — FUNDAMENTALS
## How humanity knows what the weather will do

---

## 1.1 The four ways to observe the sky

Everything in weather science comes from exactly four families of observation.
Hold this in your head — the entire architecture of PRAVAAH is built on it.

| # | Family | What it does | Its strength | Its weakness |
|---|---|---|---|---|
| 1 | **Ground observation** | A physical instrument on the ground measures what is happening *at that spot* | **Most accurate.** It is literally measuring the thing | **One spot.** Delhi has ~2 official gauges for 1,484 km² |
| 2 | **Radar** | A ground dish fires radio waves up and listens for echoes off raindrops | Fine detail (~1 km), fast (10 min), sees *inside* a storm | Range ~250 km, blocked by hills, needs calibration |
| 3 | **Satellite** | An instrument in orbit measures energy coming off cloud tops | **Covers everywhere**, including oceans and places with no infrastructure | It infers rain from the top of the cloud — an *estimate*, not a measurement |
| 4 | **Numerical model (NWP)** | A supercomputer simulates the physics of the atmosphere forward in time | The **only** thing that can tell you about *tomorrow* | It is a simulation. It drifts. It takes hours to run |

**The plain-English version:**
> A gauge is a **bucket** — perfectly accurate, but only where the bucket is.
> A radar is a **torch** — you sweep it around and see a lot, but only nearby.
> A satellite is a **camera in space** — it sees everything but has to guess.
> NWP is a **physics engine in a video game** — the only one that can run forward.

**No single one is enough.** That is the entire scientific justification for
"fusion" and it is the sentence to say to a judge:

> *"Every observing system is wrong in a different way. A gauge is right but
> blind. A satellite sees everywhere but underestimates convection. A model can
> see tomorrow but drifts. Fusion means putting all four in the same row so the
> algorithm can learn which one to trust in which situation."*

---

## 1.2 Rain gauges — the oldest and still the most trusted

**What it is:** a calibrated funnel. Rain falls in, a tipping bucket flips every
0.2 mm, a counter records the flip.

**Why it matters to us:** a gauge is **ground truth**. When we say Safdarjung
recorded 228 mm on 28 June 2024, that is a bucket that actually filled 228 times
over. Nothing else in this project is that direct.

**The problem:** India has roughly 4,000 automatic weather stations for
3.28 million km². That is one station per ~800 km². Delhi's headline number
comes from **Safdarjung (WMO 421820)** and **Palam (421810)**. Two points for
30 million people.

**How gauges reach us:** IMD does not publish raw gauge data openly. But IMD
*does* publish a **gridded product** built from those gauges —
`IMD 0.25° daily rainfall`, available through the `imdlib` Python package, free,
no account. That is our gauge-derived truth layer. Coverage 1901–2024.

> **Key limitation to state out loud:** IMD gridded is **0.25°**, which over the
> Delhi NCR box is only **6 cells**. It is an excellent *daily areal* truth. It
> cannot tell you which ward flooded. Say this before a judge finds it.

---

## 1.3 Weather radar — and what the Doppler effect actually is

### The basic idea

A radar dish fires a pulse of microwave radio energy into the sky. If the pulse
hits raindrops, a tiny fraction bounces back. The dish listens.

Two numbers come back:
1. **How long it took** → how far away the rain is (radio travels at light speed,
   so time × speed ÷ 2 = distance).
2. **How strong the echo was** → how much rain is there. Called **reflectivity**,
   measured in **dBZ**. Bigger and more numerous drops reflect more.

The dish spins 360° and tilts through several elevation angles, building a 3-D
picture of the storm. One full sweep takes about 10 minutes. That cadence is
why radar owns the nowcast.

### The Doppler effect — in plain words

You already know this effect. **An ambulance siren sounds higher-pitched coming
towards you and lower-pitched going away.** The siren itself never changes. What
changes is that the source is moving relative to you, so the wavefronts get
squashed together (higher frequency) or stretched apart (lower frequency).

**A Doppler radar does exactly the same thing with radio waves and raindrops.**

- Raindrops moving **towards** the dish squash the returning wave → frequency
  shifts **up**.
- Raindrops moving **away** squash it less → frequency shifts **down**.

Measure that frequency shift and you get **radial velocity** — how fast the rain
is moving towards or away from the radar.

### Why that is a superpower

Plain reflectivity tells you *where the rain is*. Doppler tells you *where it is
going and how violently it is rotating*.

- If one part of a storm shows air moving towards the dish and the immediately
  adjacent part shows air moving away, you are looking at **rotation** — that is
  how a mesocyclone (tornado precursor) is detected.
- Converging winds at low level means air is being forced upward — that is how
  you spot a storm about to intensify **before** the rain appears.

**The formula, if anyone pushes:**

```
Δf = (2 · v · f₀) / c
```
where `Δf` is the observed frequency shift, `v` the radial velocity of the
target, `f₀` the transmitted frequency, and `c` the speed of light. The factor of
2 is because the wave makes a round trip.

### India's radar network, and our exact position on it

IMD operates a network of **Doppler Weather Radars (DWR)**, including one at
**Delhi (Palam)**.

- **Raw volume scans** — the full 3-D data cube — are **gated**. Not public.
- **Imagery** — rendered GIF products — **is** public at
  `mausam.imd.gov.in`.

The products we log:
| Product code | Full name | What it is |
|---|---|---|
| `sri_delhi.gif` | **Surface Rainfall Intensity** | An actual **rain-rate** image, mm/hr, with a colour legend |
| `caz_delhi.gif` | Constant Altitude Z | Reflectivity at a fixed height |
| `ppz_delhi.gif` | Plan Position Z | Reflectivity at the lowest sweep |

> **Note for accuracy:** the charter originally assumed the URL pattern
> `max_dwr_{site}.gif`. That 404s on every site. The real product codes above
> were found by scraping IMD's own radar page. Chennai 404s on this naming and
> was dropped rather than left silently erroring.

**Our honest position, stated on our own slide:**
> *"We **log and display** IMD's public radar imagery every 10 minutes. We do
> **not** decode it — no model consumes those pixels in v0. Radar is THE
> nowcasting instrument, so our 0–6 hour skill is bounded by its absence. The
> raw-volume adapter is written and slots in the day access is granted."*

**Why this is not fatal:** because we say it first. A limitation you state
yourself is a credential. A limitation a judge discovers is a wound.

---

## 1.4 Weather satellites — how a machine in orbit "sees" rain

### Two orbits, two jobs

| | **Geostationary (GEO)** | **Low Earth Orbit (LEO)** |
|---|---|---|
| Altitude | ~35,786 km | ~400–800 km |
| Motion | Matches Earth's rotation — **appears to hover** over one spot | Circles the Earth every ~90 min, passing over each point ~twice a day |
| Gives you | **Constant watch** of one hemisphere, every 10–15 min | **High detail**, but only when it happens to fly over |
| India's | **INSAT-3D / 3DR** (ISRO) | — |
| Global | GOES (US), Meteosat (EU), Himawari (Japan) | **GPM Core Observatory** (NASA/JAXA) |

**The trade-off in one line:** GEO gives you *when*, LEO gives you *what*.

### How a satellite actually detects rain — three methods

**1. Infrared (IR) — the indirect guess.**
The satellite measures the temperature of the cloud top. Physics: the higher a
cloud grows, the colder its top. Tall clouds are usually storm clouds. So *cold
top → probably raining hard*.

**This is an inference, not a measurement.** A cold cirrus sheet with no rain in
it looks identical to a thunderstorm from above. This is why IR-only rain
estimates are noisy.

**2. Passive microwave — the better physics.**
Water and ice interact with microwave radiation in ways that depend on the actual
particles. Ice scattering aloft depresses the signal at high frequency; liquid
water emits at low frequency over ocean. So a microwave sensor is genuinely
sensing **hydrometeors inside the cloud**, not just the roof.

Much more physical — but the sensors sit on **LEO** satellites, so you only get
a snapshot when one flies over.

**3. Spaceborne radar — the gold standard.**
The **GPM Core Observatory** carries the **Dual-frequency Precipitation Radar
(DPR)** — an actual radar in space, firing down and reading the 3-D structure of
rain. This is the most accurate space-based rain measurement that exists.

**Its fatal flaw for us:** it is a **narrow swath, twice a day.** You cannot
build a 10-minute nowcast from something that passes over twice a day. We
evaluated it and rejected it for exactly this reason — *wrong cadence, not wrong
instrument.*

### IMERG — how the three are combined

**IMERG** = *Integrated Multi-satellitE Retrievals for GPM*. NASA's flagship
rainfall product, and the one we pulled.

What it does: takes the **accurate but rare** passive-microwave overpasses,
uses the **frequent but crude** infrared from geostationary satellites to fill
the gaps in between, calibrates everything against the **GPM DPR** space radar,
and then adjusts against gauges where they exist.

**Result:** rainfall everywhere on Earth, **0.1° grid, every 30 minutes,
2000–present.** Free.

We pulled 976 monsoon days over 48 cells. See §3.3 for why we tested it and did
not ship it — and §8.5 for why that decision may reverse in v1.

### One more satellite type you should be able to name: SAR

**Synthetic Aperture Radar (Sentinel-1, ESA).** A radar in orbit pointed
sideways at the ground.

**Why it matters for flooding:** radar **sees through cloud**. Optical satellites
(Sentinel-2, normal imagery) are **cloud-blind exactly when it floods** — the
flood is under the storm. SAR is not. And water is **smooth**, so it reflects
radar away from the sensor and appears **dark**. Compare a before-image and an
after-image and flood extent falls out almost automatically.

**This is the single most important dataset for our roadmap** — see §8.5.

---

## 1.5 NWP — what a physics simulation of the atmosphere really is

### The plain-English version

Divide the entire atmosphere into a 3-D grid of boxes. For each box, record
temperature, pressure, humidity, and wind. Now apply the laws of physics —
fluid dynamics, thermodynamics, radiation — to compute what each box will look
like a few seconds later. Then repeat. Millions of times.

That is **Numerical Weather Prediction.** It is a video-game physics engine for
the sky, running on a supercomputer.

### The three models we use — name them correctly

| Model | Full name | Run by | We access via |
|---|---|---|---|
| **IFS** | Integrated Forecasting System | **ECMWF** (European Centre for Medium-Range Weather Forecasts) | Open-Meteo, model id `ecmwf_ifs025` |
| **GFS** | Global Forecast System | **NOAA** (US) | Open-Meteo, model id `gfs_seamless` |
| **ICON** | ICOsahedral Nonhydrostatic | **DWD** (German Weather Service) | Open-Meteo, model id `icon_seamless` |

India's own are **NCUM** and **BharatFS** (run by NCMRWF/IMD). Both gated. Both
listed as queued adapters — each would land as one new ablation row.

### Why NWP is useless in the next 3 hours — the crucial point

Three compounding reasons:

1. **It runs on fixed cycles.** A global model runs 4× a day (00Z, 06Z, 12Z,
   18Z). If it is 09:00 and you need the next 2 hours, the freshest run started
   at 06:00.
2. **It takes hours to compute.** A 00Z global run is not on the wire until
   roughly 05–06Z. *(This is exactly why our leakage gating stamps NWP as
   available at `valid_time.normalize() + 6h` — deliberately conservative.)*
3. **Spin-up.** In its first hours a model is still settling its own physics
   into balance. Its early output is the least reliable part of the run.

**Result: in the 0–6 hour window there is effectively no skilful, fine-grained
public NWP guidance.** That is not our opinion. **We measured it:**

> **Raw GFS scores CSI 0.009–0.015 at 0–6 hours on our test year.**
> That number *is* the 0–6 hour hole. Put it on a slide.

### And why NWP is essential at 24–72 hours

Beyond ~6 hours, observations are worthless — knowing where a rain blob sits
right now tells you nothing about tomorrow afternoon. Only physics can propagate
that far. So NWP goes from near-useless to *the only game in town*, and the
crossover is around 6 hours.

**Our two models sit on either side of that crossover. That is the design.**

---

## 1.6 Reanalysis (ERA5) — the answer key, and why it is not a forecast

### What reanalysis is

Take a modern NWP model. Now run it over the **past**, and at every step feed it
**every observation that was ever recorded** at that moment — gauges, radiosonde
balloons, aircraft, ships, satellites. The model is continuously nudged back
towards reality by data.

**The output is not a forecast. It is a physically consistent, gap-free
reconstruction of what the atmosphere actually did.**

**ERA5** is ECMWF's version: hourly, global, 1940–present.
**ERA5-Land** is a higher-resolution land-surface version, ~9 km. This is ours.

### Why we use it

Because we need an **answer key**. To train a model to predict rain, you need to
know how much rain actually fell — at *every* lattice point, at *every* hour, for
*eight years*. Gauges cannot do that (two stations). Satellites are estimates.
**ERA5 is the only source that gives a complete, hourly, gridded answer for free
with no account.**

### Why it hurts us — say this before a judge finds it

**ERA5 is a ~9 km reanalysis, and reanalyses smooth convective extremes.**

On 28 June 2024, near Safdarjung:

| Source | Reading | Rank in 2024 |
|---|---:|---|
| Real gauge | **228 mm** | the event of the year |
| IMD gridded (gauge-based) | **150.7 mm** | **#1 wettest day** ✅ |
| IMERG (satellite) | 32.9 mm | — |
| **ERA5-Land** (reanalysis) | **20.9 mm** | **not in the top 8** ❌ |

**The consequence is load-bearing, not trivia:**
> A model trained only on ERA5 learns to predict *smoothed* rain, and can never
> predict a cloudburst — **because its answer key never contains one.**

**What ERA5 still does well:** its *timing* is correct. Its peak lands at 22:00Z
27 June = 03:30 IST 28 June, matching the reported cloudburst. So ERA5 keeps its
job for **hourly structure** — lags, accumulations, antecedent indices — and IMD
gridded takes over as truth for the **daily exceedance categories**.

*(Note the timezone trap this exposes: the event is "28 June" in IST but
straddles 27 June in UTC. Rule R8 — UTC internally, always — is what stops this
silently halving the event.)*

---

## 1.7 The forecast timeline — nowcast vs forecast, and the hole

```
   NOW          +1h      +3h      +6h              +24h            +72h
    │            │        │        │                 │               │
    ├────────────────────────────────┤                               │
    │      NOWCASTING                │                               │
    │  driven by OBSERVATIONS        │                               │
    │  "where is the rain, where     │                               │
    │   is it drifting"              │                               │
    │        ← RainCast-v0 →         │                               │
    │                                │                               │
    │                    ├───────────────────────────────────────────┤
    │                    │        FORECASTING                        │
    │                    │  driven by PHYSICS (NWP)                  │
    │                    │  "what will the atmosphere do"            │
    │                    │        ← RainFuse-v0 →                    │
    │                    │                                           │
    └────────────────────┴───────────────────────────────────────────┘
              ▲
        THE 0–6 HOUR HOLE
     NWP too slow and too coarse.
     Radar would fill it — but raw
     radar is gated in India.
     Measured: raw GFS CSI = 0.015
```

**Nowcasting** = very-short-range forecasting driven mainly by **extrapolating
current observations** rather than by simulating physics. Where is the rain
*now*, which direction is it drifting, is it growing or decaying.

**Operational difference, in the words a control room uses:**
- Nowcast → **"Evacuate that underpass NOW."**
- Forecast → **"Position pumps and staff for tomorrow's shift."**

**And our own ablation table proves the crossover empirically:**

| At 0–6 h | CSI |
|---|---:|
| without NWP | **0.124** |
| ALL SOURCES | 0.098 |
| raw GFS alone | **0.015** |

Removing NWP **improved** the nowcast. Meanwhile at 24 h, RainFuse's entire value
comes from NWP being the signal. **That is one coherent result, not two
contradictory ones:** observations own the short range, physics owns the long
range.

---

## 1.8 Rain ≠ flood — the hydrology you need in your head

**The single most important sentence in this project:**

> **50 mm on a low-lying, sealed, badly-drained cell with saturated soil floods.
> The same 50 mm two streets uphill does not.**

A millimetre number is not a decision. Something has to convert rain into
**water on the ground**, and then into **who is affected**. That conversion is
our USP.

### The terms, in plain words

| Term | Plain English | Why it matters |
|---|---|---|
| **DEM** | *Digital Elevation Model.* A picture where every pixel's value is the **height of the ground**, not its colour. Ours is Copernicus GLO-30 at 30 m | Everything hydrological is derived from it |
| **Flow direction** | For each cell, which of its 8 neighbours would water run to? (Downhill) | The plumbing diagram of the landscape |
| **Flow accumulation** | Following those arrows, how many upstream cells drain **through** this cell? | High accumulation = a natural stream forms here |
| **HAND** | *Height Above Nearest Drainage.* For each cell: how far **vertically** does it sit above the nearest stream it drains into? | **Low HAND = water collects here.** Classically the strongest single predictor of flooding |
| **TWI** | *Topographic Wetness Index* = `ln(flow_accumulation / tan(slope))` | Big upslope area + flat ground = wet. High TWI = soggy |
| **Slope** | Steepness | Steep sheds water, flat holds it |
| **Impervious fraction** | What share of a cell is **sealed** — concrete, asphalt, roof | Sealed ground does not absorb. It routes water downhill fast |
| **API** | *Antecedent Precipitation Index* — a weighted sum of recent rain | **Already-saturated soil floods faster.** (Not a web API!) |
| **Distance-to-drain** | How far to the nearest mapped drain/canal/river | Far from drainage = nowhere for water to go |

### The classical picture, and why it broke for Delhi

The textbook says: **low HAND + high TWI + flat + impervious + far from drain =
floods.** We built exactly that map. And it **failed** on Delhi's real blackspots.

Two independent measurements said so:
- Of six known waterlogging wards, only **MINTO ROAD** reached the top quintile.
  **Jama Masjid: 3.1st percentile. Turkman Gate: 7.6th** — while being 92% and
  100% impervious.
- Label enrichment in high-susceptibility cells: **0.94** — labelled flood points
  were, if anything, *slightly less* likely to sit in "flood-prone" terrain than
  a random cell.

**Why it broke — two reasons, both physical:**

1. **The DEM is a DSM, not a DTM.**
   A *Digital Surface Model* includes **buildings and trees**. A *Digital
   Terrain Model* is bare earth. Copernicus GLO-30 is a **surface** model. So in
   the dense old city, the "terrain height" the algorithm sees is partly
   **rooftop height**. HAND reads **14.9 m at Jama Masjid** — the algorithm
   thinks the old city is on a hill. It is measuring roofs.

2. **Delhi's flooding is PLUVIAL, not FLUVIAL.**
   - *Fluvial* = river bursts its banks. Classical terrain hydrology finds this.
   - *Pluvial* = rain falls faster than the drains can carry it away. Terrain
     barely matters; **drainage capacity** does.

   Three of our four checkpoint blackspots are **underpasses** — 5–15 m
   engineered dips that a 30 m DEM physically cannot resolve.

### The breakthrough: proxying a dataset that does not exist

**Storm-sewer capacity is not open data anywhere in India.** But the *structures*
are: **OpenStreetMap tags every underpass** with `tunnel=yes` or `layer<0`.

We pulled **1,305 below-grade ways** and **7,329 bridges** and computed, for
every 100 m cell, the distance to the nearest one.

| Distance to nearest below-grade way | |
|---|---:|
| Minto Bridge | **0 m** |
| ITO | 100 m |
| Zakhira | 300 m |
| Pul Prahladpur | 1,281 m |
| **City-wide median** | **2,746 m** |

| InundaNet | before | after |
|---|---:|---:|
| AUC-PR (5 km spatial-block CV) | 0.498 | **0.611** |
| matched-negative ROC-AUC | 0.829 | **0.918** |
| lift over HAND-only baseline | 8.0× | **9.8×** |

`underpass_dist` became the **#2 feature**. Pahar Ganj went from the 13.8th to
the **87.9th percentile**.

> **🎤 This is the intellectual contribution of the project. Lead with it.**
>
> *"Classical flood hydrology could not find Delhi's blackspots, and we can show
> you the numbers where it failed. The reason is that Delhi floods at
> underpasses, from drainage-capacity failure, not topography — and drainage
> capacity is not open data anywhere in India. So we found a proxy: OpenStreetMap
> tags every underpass. That single feature took our AUC-PR from 0.50 to 0.61."*

---

## 1.9 🎤 JUDGE QUESTIONS — fundamentals

**"How does a satellite actually measure rainfall?"**
> Three ways, and IMERG combines all three. Infrared reads cloud-top temperature
> — cold top means tall cloud means probably heavy rain, but that is an inference
> and a cold cirrus sheet fools it. Passive microwave actually senses the ice and
> water particles inside the cloud — much more physical, but it flies on low-Earth
> orbit so you only get a snapshot twice a day. And the GPM Core Observatory
> carries an actual radar in space, the DPR, which is the gold standard but is a
> narrow swath. IMERG uses the accurate-but-rare microwave, fills the gaps with
> the frequent-but-crude infrared, and calibrates against the space radar and
> gauges. That gives 0.1 degree every 30 minutes, globally.

**"Explain the Doppler effect and why weather radar uses it."**
> Same effect as an ambulance siren sounding higher-pitched as it approaches. A
> radar fires a radio pulse; raindrops moving towards the dish shift the returning
> frequency up, drops moving away shift it down. Measure the shift and you get
> radial velocity. Plain reflectivity tells you where the rain is; Doppler tells
> you where it is going and whether it is rotating. Adjacent towards-and-away
> signatures reveal a mesocyclone. And converging low-level winds mean air is
> being forced upward, which lets you see a storm about to intensify before the
> rain even appears.

**"Why can't NWP just do the nowcast too?"**
> Three compounding reasons. It runs on fixed six-hourly cycles, so your freshest
> run may already be three hours old. It takes hours of supercomputer time, so a
> 00Z run is not on the wire until 05 or 06Z. And it has spin-up — its first
> hours are the least reliable part of the run while the physics settles. We
> measured the consequence rather than asserting it: raw GFS scores CSI 0.015 in
> the 0–6 hour window on our test year. That number is the gap we exist to fill.

**"What is the difference between a forecast and a reanalysis?"**
> A forecast runs forward from now into the unknown. A reanalysis runs the same
> physics over the past while continuously feeding in every observation ever
> recorded, so the model is constantly nudged back towards reality. The output is
> not a prediction — it is a physically consistent, gap-free reconstruction of
> what actually happened. We use ERA5-Land as our answer key because it is the
> only source that gives complete hourly gridded rainfall for eight years, free
> and with no account.

**"Why is HAND the standard flood predictor, and did it work for you?"**
> HAND is Height Above Nearest Drainage — for every cell, how far vertically it
> sits above the stream it drains into. Low HAND means water collects there. It
> is normally the strongest single predictor. **For Delhi it failed, and we can
> prove it: our label enrichment in high-HAND-susceptibility cells was 0.94 —
> essentially random.** Two reasons. The Copernicus DEM is a surface model, so in
> the dense old city it is measuring rooftops — HAND reads 14.9 metres at Jama
> Masjid. And Delhi's flooding is pluvial, not fluvial: it floods when rain beats
> the drains, not when a river rises. That finding is why we went looking for a
> drainage proxy, and why underpass distance is now our number two feature.

---
---

# PART 2 — THE PROBLEM STATEMENT AND OUR ANSWER

---

## 2.1 SIH26071, stated exactly

| | |
|---|---|
| **Problem ID** | **SIH26071** |
| **Ministry** | Ministry of Earth Sciences (**MoES**) / India Meteorological Department (**IMD**) |
| **Theme** | Software / Disaster Management |
| **The ask** | AI/ML-based prediction of **heavy rainfall and consequent inundation**, using satellite, radar, observational and NWP model data, **with enough lead time for authorities to act** |

Read the ask carefully. It contains **three** requirements, and most teams will
only deliver the first:

1. Predict heavy rainfall ✅ (everyone does this)
2. **And consequent inundation** ✅ (almost nobody does this — this is our USP)
3. **With enough lead time to act** ✅ (this is why the 0–6 h nowcast matters)

Also note "using satellite, radar, observational and NWP model data" — **four
source families are named in the problem statement itself.** That is why fusion
is not a design flourish; it is a literal requirement.

---

## 2.2 The four gaps we exist to close

| Gap | What it means operationally |
|---|---|
| **The 0–6 hour hole** | NWP runs on fixed cycles and takes hours. In the window that matters most for an urban cloudburst — the next 1 to 6 hours — there is effectively no skilful, fine-grained public guidance. **Measured: raw GFS CSI 0.015.** |
| **Warnings are district-scale** | An IMD warning says *"Delhi: heavy rain."* A control room needs *"Minto Bridge underpass, 78%, water by 06:30."* A district colour code cannot be actioned at ward level. |
| **Rain ≠ flood** | A millimetre number is not a decision. Nobody converts the rain forecast into water on the ground and then into who is affected. |
| **Data is siloed** | Satellite, radar, gauge and model data live in separate systems with separate formats, cadences and access regimes. No one fuses them into a single learnable representation. |

---

## 2.3 What PRAVAAH actually is, in one paragraph

> **PRAVAAH** (Hindi **प्रवाह**, "flow") = *Predictive Rainfall, Accumulation and
> Vulnerability Analytics for Anticipatory Hazard response.*
>
> Five families of free, open data are pulled through **adapters** that all emit
> one shared record shape, joined into a single **fusion cube** where every row
> is one place at one hour and every source's opinion sits side by side. Three
> **LightGBM** models read that cube: **RainCast** nowcasts 0–6 h rain from
> observations, **RainFuse** corrects and calibrates the 6–72 h NWP physics, and
> **InundaNet** converts rain into flood probability at 100 m, which is
> aggregated to **289 wards** and joined to an exposure table to answer *who is
> affected*. Every probability is **isotonic-calibrated on a held-out year**.
> Outputs are precomputed into static files, so the demo runs **offline**, and a
> **live pipeline** refreshes the same files from current conditions on demand.

---

## 2.4 The four proofs — our definition of "done"

Judges are not convinced by "we used AI." They are convinced by **checkable
artefacts.** Every task in this project exists to produce one of four proofs.

| # | Proof | Artefact | Current status |
|---|---|---|---|
| **P-1** | **Fusion works** | An **ablation table** — retrain with one source family removed, re-score | ⚠️ **NEGATIVE RESULT, KEPT.** Removing NWP *improves* the 0–6 h model. Diagnosed, not hidden — see §9.2 |
| **P-2** | **Calibration is real** | A **reliability diagram** — when we say 80%, it happens ~80% of the time | ✅ **RainFuse Brier 0.0112 vs raw NWP 0.0401 — 3.6× better calibrated** |
| **P-3** | **Lead time is gained** | Minutes gained over IMD's own CAP alert stream | ❌ **NOT COMPUTABLE for this event, and we say so** — see §9.2 |
| **P-4** | **It is portable** | A new region = **one YAML file**, no code change | ✅ `configs/aoi_chennai.yaml` loads through the pipeline, zero Python changed |

**These four proofs are the definition of done.** A beautiful UI with no ablation
table loses. An ablation table with no UI loses.

**Two of the four are honest failures.** That is not a weakness if you own it —
see §9.4 for exactly how to say it.

---

## 2.5 Why Delhi NCR is the pilot

India's two best urban flood-warning systems are **iFLOWS-Mumbai** and
**CFLOWS-Chennai**. Both are excellent. Both took **years** to build. Both
required a **bespoke bathymetry survey** of the city's drainage. Both cover
exactly **one city each**.

**Delhi NCR — a 30-million-person capital region with a documented, repeating
urban-flooding problem — has neither.**

It also has, uniquely:
- The best open waterlogging labels in the country (Delhi PWD and Delhi Traffic
  Police publish named recurring locations — Minto Bridge, ITO, Zakhira, Pul
  Prahladpur).
- A rich, well-documented event catalogue.
- A public IMD radar site (Delhi DWR) whose imagery is openly polled.

**Pilot box:** `76.85–77.65 °E, 28.30–28.95 °N` — 0.80° lon × 0.65° lat ≈
**78 km × 72 km**.

> **Crucial framing, say it exactly:** *"The **rainfall layer is region-agnostic**
> — it is grid-based and runs anywhere. Only the **inundation layer** is
> Delhi-specific, because inundation needs per-city terrain and per-city labels."*

---

## 2.6 🎤 JUDGE QUESTIONS — scope and framing

**"How is this different from iFLOWS / CFLOWS?"**
> Those are excellent NWP-plus-gauge-plus-2D-hydrodynamic systems for two cities,
> each needing a bathymetry survey and years of work. We add three things they do
> not have. First, the **0–6 hour learned nowcast** — they are NWP-driven and do
> not fill that window. Second, we **learn inundation from labels instead of
> surveying drainage**, which is why we can stand up a new district from a config
> file rather than a field campaign. Third, everything is **calibrated
> probability**, not a deterministic water level. Delhi has no iFLOWS. We built
> its equivalent from open data and made it portable.

**"So you are just doing what IMD already does?"**
> No — we sit **downstream** of IMD and fill in what a district warning cannot
> express. IMD issues authoritative district-scale bulletins. We take that class
> of information and answer the two questions a control room actually asks: *which
> ward, and by when.* And we use IMD's own official categories — 64.5, 115.6 and
> 204.5 mm — so our output maps directly onto IMD's own warning language rather
> than competing with it.

**"Why should we believe a hackathon team on a problem that took Mumbai years?"**
> Because we are not claiming to have done what Mumbai did. Mumbai built a
> physics-based 2D hydrodynamic model on a surveyed drainage network — that is a
> different and in many ways better thing, and it costs years. We built a
> **learned** system on open data, which is weaker per-city and far cheaper to
> replicate. The honest comparison is not "ours is better" — it is "ours can
> exist in cities that will never get a bathymetry survey."

---
---

# PART 3 — THE DATA: every byte, and where it came from

---

## 3.1 The master source table — exact names, exact endpoints

**Everything below is free. `Access` states the exact requirement.**

### Actively used in v0 (8 sources, ~1.1 GB on disk)

| ID | Exact source | Exact endpoint / package | What we got | Access |
|---|---|---|---|---|
| **A1** | **ERA5-Land** hourly reanalysis (ECMWF), served by **Open-Meteo Archive** | `archive-api.open-meteo.com/v1/archive` | 56 pts × 64,704 hrs = **3.6 M rows, 80 MB**, 2018-05-15 → 2025-09-30 | **none** |
| **A2** | **Open-Meteo Historical Forecast API** — past NWP runs *as issued* | `historical-forecast-api.open-meteo.com` | 56 pts, 3 models + CAPE/CIN/lifted index, **2.33 M rows, 30 MB** | **none** |
| **A2w** | Same, **wide NW-India domain** | same endpoint | **195 pts, 95 MB** | **none** |
| **A4** | **NASA GPM IMERG V07** satellite rainfall | Google Earth Engine `NASA/GPM_L3/IMERG_V07` | 976 monsoon days, 48 cells, 30-min | GEE project (active) |
| **A5** | **ESA WorldCover v200** (10 m landcover) + **GHSL GHS-BUILT-S R2023A** | AWS `s3://esa-worldcover` (unsigned) + `ghsl.jrc.ec.europa.eu` | 3 rasters → impervious fraction, built-up | **none** |
| **A7** | **Copernicus GLO-30 DEM** | `s3://copernicus-dem-30m` (unsigned boto3), tiles `N28 E076`, `N28 E077` | 5 rasters → HAND, TWI, slope, curvature, flow-acc | **none** |
| **A9** | **OpenStreetMap** via Overpass / `osmnx` | `overpass-api.de`, `download.geofabrik.de/asia/india` | 5 files, 29 MB — drains, hospitals, schools, pumps, roads, **1,305 underpasses** | **none** |
| **A11** | **IMD gridded 0.25° daily rainfall** (IMD Pune) | `imdlib` Python package | NCR + wide domain, **2,793 cells**, 2018–2024 | **none** |
| **+** | **GHS-POP R2023A** 100 m population | `ghsl.jrc.ec.europa.eu` | Delhi total **20.7 M** — matches published NCT figures | **none** |
| **+** | **DataMeet** ward polygons | `github.com/datameet/Municipal_Spatial_Data` → `Delhi/Delhi_Wards.geojson` | **290 polygons**, 289 in AOI | **none** |

### Live loggers (running continuously since 28 Aug 2026)

| ID | Source | Endpoint | Cadence | Captured so far |
|---|---|---|---|---|
| **A3** | Open-Meteo Forecast (live) | `api.open-meteo.com/v1/forecast` | 60 min | 9 pulls |
| **A14** | **IMD DWR radar imagery** | `mausam.imd.gov.in` → `sri_delhi.gif`, `caz_delhi.gif`, `ppz_delhi.gif` | 10 min | **37 GIFs** |
| **A15** | **IMD CAP alerts** | `cap-sources.s3.amazonaws.com/in-imd-en/rss.xml` | 15 min | polling |
| **A16** | **ECMWF open data** | `ecmwf-opendata` package | 4× daily | 5 runs |

### Not pulled (and why that is fine)

**A6** (Global Flood Database), **A8** (`s3://glo-30-hand` — actually *was* used
as a cross-check), **A12** (CHIRPS), **A13** (NOAA ISD stations), **A17** (gated
agency adapters).

> **The honest line:** *"A12 and A13 are low-value additions. A6 is a genuine
> miss — more flood labels would help, and it is first on the v1 list. A17 are
> the gated agency feeds; nothing in v0 depends on any of them, and each approval
> lands as exactly one new ablation row."*

### One addition that was not in the charter at all

**OSM underpass tags.** Not planned, not in the original design, and it turned
out to be **our best feature.** That is worth saying out loud — it shows the
project responded to measurement rather than to plan.

---

## 3.2 What each source physically is

Pair this with §1.1–1.6 — this is the "which of the four families is it" mapping.

| Source | Which family | What it physically is |
|---|---|---|
| A1 ERA5-Land | **Model (reanalysis)** | A physics reconstruction of the past, nudged by observations. ~9 km, hourly |
| A2 / A2w | **Model (NWP)** | Actual past forecasts, saved with the timestamp at which they were issued |
| A4 IMERG | **Satellite** | Microwave + infrared + space radar, merged. 0.1°, 30 min |
| A5 WorldCover / GHSL | **Static** | A land-cover classification per 10 m pixel; built-up surface in m² per cell |
| A7 Copernicus DEM | **Static** | Ground (surface) height per 30 m pixel, from radar interferometry |
| A9 OSM | **Static** | Human-drawn map of what people built |
| A11 IMD gridded | **Ground observation** | Interpolated from real IMD rain gauges. **The only gauge-based source we have** |
| A14 IMD radar | **Radar** | Rendered images of Delhi DWR sweeps. **Displayed, not decoded** |
| A15 IMD CAP | **Benchmark** | Official alert XML *with timestamps* — our lead-time reference |

---

## 3.3 What we evaluated and rejected — and the honest reason

> Being able to say *"we evaluated it and excluded it, here is why"* scores more
> points than silently not using something.

| Rejected | The honest reason |
|---|---|
| **Sentinel-2 for flood mapping** | **Optical — cloud-blind exactly when it floods.** The flood is under the storm. Sentinel-1 SAR is the correct instrument and is on the roadmap |
| **GPM DPR "satellite radar"** | Real radar, **wrong cadence**. A narrow swath twice a day cannot drive a 10-minute nowcast |
| **Bhuvan bulk tiles** | Heavy and login-gated for bulk. May appear later as an optional ISRO basemap toggle; **not a model input** |
| **Kaggle / Colab GPUs** | Nothing in v0 needs a GPU. LightGBM trains in under a minute on CPU. **The bottleneck is data wrangling, not compute** |
| **NASADEM** | No advantage over Copernicus GLO-30, which is already scripted |
| **IMERG as a RainCast feature** | ⚠️ **Tested head-to-head and NOT shipped.** See below |

### The IMERG experiment — a genuinely instructive negative

We pulled 976 monsoon days of 30-minute IMERG, built 24 features including
intra-hour trend and 30-minute advection, and ran a clean A/B on **identical
code**:

| | mean CSI across 12 heads |
|---|---:|
| ERA5 features only | **0.0728** |
| ERA5 + IMERG | 0.0718 |

Only **4 of 12 heads improved**, and those four are the thinnest (`acc20_w1` has
22 test positives). The best-populated heads got **worse**.

**The diagnosed cause — and this is the interesting part:**
> **Our target is ERA5-derived.** So ERA5 features are its natural best
> predictors, and IMERG enters as a **noisy proxy for our label** rather than as
> new information about reality. IMERG was measuring reality *more accurately* —
> and got punished for it, because reality disagreed with the answer key.

**Not shipped. Archive kept.** Recorded in `reports/imerg_experiment.json`.

> **🎤 This is a great answer to "did you just throw data at it?"**
> *"No — we A/B tested every family. IMERG cost us 976 days of pulling and we
> did not ship it, because on identical code it made the model slightly worse.
> We can show you the JSON. And we diagnosed why rather than shrugging: our
> target is ERA5-derived, so a more accurate satellite product registers as noise
> relative to a smoothed label. Fix the target and IMERG likely becomes valuable
> in the same experiment that just rejected it."*

---

## 3.4 The 228 mm story — when three truth sources disagree

This is the single best data story in the project. Learn it cold.

**28 June 2024.** Safdarjung recorded **228 mm** — the highest June daily total
since **1936**. The IGI airport terminal canopy collapsed.

| Source | Type | Reading near Safdarjung | Rank among 2024 NCR days |
|---|---|---:|---|
| **Reality** (IMD station) | gauge | **228 mm** | the event of the year |
| **IMD gridded 0.25°** | gauge-interpolated | **150.7 mm** | **#1 wettest day of 2024** ✅ |
| **IMERG 0.1°** | satellite | 32.9 mm | — |
| **ERA5-Land ~9 km** | reanalysis | **20.9 mm** | **not in the top 8** ❌ |

### Read the ordering carefully — this is the point

**This is NOT a resolution ranking.** IMERG is *finer* (0.1°) than IMD gridded
(0.25°) and still reads lower.

**It is a MEASUREMENT-TYPE ranking:**
- **Gauge-based captures the extreme** — it is physically catching the water.
- **Satellite retrieval underestimates convection** — it is inferring rain from
  above the cloud.
- **Reanalysis smooths hardest** — it is a coarse physics model averaging over
  ~9 km, and a cloudburst is smaller than that.

### The five consequences — all load-bearing

1. **ERA5 must not be the sole training target for heavy-rain exceedance.** A
   model trained only on ERA5 learns to predict *smoothed* rain.
2. **IMD gridded becomes the truth layer for the daily exceedance heads**
   (RainFuse: 64.5 / 115.6 / 204.5 mm). Those are IMD's **own official
   categories** — verifying them against IMD's **own observational product** is
   the most defensible choice available in front of IMD judges.
3. **ERA5 keeps its job:** hourly structure — lags, accumulations, antecedent
   indices. IMD gridded is daily only and cannot do that.
4. **IMD gridded stops at 2024**, so the 2025 TEST split falls back to ERA5 +
   IMERG. **State this openly.**
5. **The disagreement is evidence FOR fusion, not an embarrassment.** Two truth
   sources disagree in a measurable, explainable way. That *is* the argument for
   fusing source families instead of trusting one.

> **🎤 Say it like this:**
> *"Ask us why fusion matters and this is the answer. On our flagship event the
> gauge read 228 mm, IMD's gridded product read 150.7 and ranked it the wettest
> day of the year, the satellite read 32.9, and ERA5 read 20.9 and did not put it
> in the top eight. That is not a resolution ranking — IMERG is finer than IMD
> gridded and still reads lower. It is a measurement-type ranking, and it is
> exactly why you cannot trust one source."*

---

## 3.5 TRAIN data vs LIVE data — two lanes that never touch

People confuse these constantly. They are completely separate systems.

```
LANE 1 — TRAINING (pulled once, frozen)
   Open-Meteo / S3 / OSM / imdlib
        │  one time, in bulk
        ▼
   data/raw/  (1.1 GB)  ──►  the cube  ──►  models trained  ──►  *.txt boosters
   Never re-fetched. A1 took 11 minutes for 3.6 M rows.

LANE 2 — LIVE LOGGERS (running forever)
   IMD radar / IMD CAP / Open-Meteo / ECMWF
        │  every 10–60 min, under caffeinate
        ▼
   data/raw/live/  ──►  37 radar GIFs, 9 Open-Meteo pulls, 5 ECMWF runs, CAP polls
   With a _lastpoll heartbeat so a dedup-quiet feed is not mistaken for a dead logger.

LANE 3 — THE DEMO (touches neither of the above)
   data/outputs/*.json  ──►  FastAPI  ──►  React
   Reads precomputed static files. Airplane-mode safe.
```

### Why the loggers exist at all — the strategic answer

> **Nobody serves an archive of live feeds.** You cannot download "what IMD's
> radar looked like last August." It does not exist anywhere. **So our loggers
> ARE the archive.**

Every day they run is **irreplaceable** training data and **irreplaceable**
benchmark timestamps that no competing team can obtain retroactively.

**The two-era strategy:**
- The **satellite era** (2015–2025) trains the models *now*.
- The **radar era** begins with our own GIF loggers. By December we would hold
  months of ~1 km radar data that no competitor has.

---

## 3.6 🎤 JUDGE QUESTIONS — data

**"Why did you not use MOSDAC / ISRO / IMD's own APIs?"**
> **We use every IMD product that is public today** — the CAP alert stream, the
> radar imagery, and the gridded rainfall, which is in fact our truth layer for
> the exceedance categories. MOSDAC, Copernicus GFM and Earthdata accounts are in
> approval queues that take weeks and we had a day. But the architecture treats
> every gated feed as an **adapter** emitting one shared record shape, so an
> approval upgrades the system with **no downstream rework** and lands as exactly
> one new ablation row. That is a design choice, not a workaround.

**"Your data is all foreign — European ECMWF, American NOAA and NASA. Where is
the Indian data?"**
> Three of our layers are Indian and two of them are load-bearing. **IMD gridded
> rainfall is our truth layer for RainFuse** — we verify against IMD's own
> official categories using IMD's own observational product. **IMD radar imagery**
> is logged every ten minutes and displayed in the product. **IMD CAP alerts** are
> our lead-time benchmark. What we do not have is *gated* Indian data — raw DWR
> volumes, the AWS gauge archive, NCUM. Those are precisely the pilot ask on our
> final slide.

**"How do you know your data is correct? Did you validate it?"**
> Yes, and it caught two bugs that would have silently corrupted the models. We
> have a rule — **fetch once, inspect the real response, then write the parser.**
> First catch: CAPE requested from the archive endpoint comes back **100% NULL**,
> 64,704 out of 64,704 rows, on every model — because CAPE is an ERA5
> single-levels field, not an ERA5-Land one. Written blind, our nowcast would have
> trained on a dead column. Second catch: the IMD join was snapped the **wrong
> direction**, giving 9.6% coverage; reversed, it gives 89.9%. Neither would have
> thrown an error. Both would have quietly degraded every number we are showing
> you.

**"Is this data free? What happens when the free tier runs out?"**
> Every source is free with **no account** except Google Earth Engine, which is
> free for non-commercial use and which we deliberately used for exports only,
> never for compute. There is no free tier to run out of — Open-Meteo, the AWS
> open-data buckets, OSM, JRC and `imdlib` are public infrastructure. In
> production you would mirror them rather than poll them, which is exactly what
> our loggers already do.

---
---

# PART 4 — GEOGRAPHY: degrees, grids, lattices and wards

---

## 4.1 What a "degree" means in kilometres

Latitude and longitude are **angles**, not distances. But you can convert:

| | Conversion | At Delhi (28.6 °N) |
|---|---|---|
| **1° latitude** | ≈ **111 km**, everywhere on Earth | 111 km |
| **1° longitude** | ≈ `111 × cos(latitude)` km | `111 × cos(28.6°)` ≈ **97.5 km** |

Longitude lines converge at the poles, which is why longitude "shrinks" as you go
north. Latitude lines are parallel, so a degree of latitude is constant.

**So for us:**
| | |
|---|---|
| **0.1° latitude** | ≈ **11.1 km** |
| **0.1° longitude at Delhi** | ≈ **9.75 km** |
| **One 0.1° cell** | ≈ 11.1 × 9.75 ≈ **108 km²** |

---

## 4.2 The 0.1° rain lattice — why exactly 56 points

From `configs/aoi_delhi_ncr.yaml` (nothing is hardcoded in Python — Rule R7):

```yaml
bbox:  west: 76.85   east: 77.65   south: 28.30   north: 28.95

rain_lattice:
  resolution_deg: 0.1
  lat_start: 28.35    lat_count: 7
  lon_start: 76.90    lon_count: 8
  expected_points: 56
```

**7 latitudes × 8 longitudes = 56 points.**

```
        76.90  77.00  77.10  77.20  77.30  77.40  77.50  77.60      lon
28.95    ·      ·      ·      ·      ·      ·      ·      ·
28.85    ·      ·      ·      ·      ·      ·      ·      ·
28.75    ·      ·      ·      ·      ·      ·      ·      ·
28.65    ·      ·      ·      ●      ·      ·      ·      ·   ← 28.65, 77.22
28.55    ·      ·      ·      ·      ·      ·      ·      ·      ≈ central Delhi
28.45    ·      ·      ·      ·      ·      ·      ·      ·
28.35    ·      ·      ·      ·      ·      ·      ·      ·
 lat
```

**Sanity check:** the box is 0.80° lon × 0.65° lat = **78 km × 72 km ≈ 5,600 km²**.
56 cells × ~108 km² ≈ 6,000 km². ✅ Consistent.

### Why 0.1° and not finer?

Because **0.1° is the native resolution of the data.** IMERG is published at
0.1°. ERA5-Land is ~9 km ≈ 0.08°. Making a 0.01° lattice would not create
information — it would interpolate the same numbers into more boxes and give a
false impression of detail. **The lattice matches the physics of the source.**

---

## 4.3 The 100 m inundation grid — why 561,600 cells

Rainfall is a broad-scale phenomenon. **Flooding is not.** Water pools in a
specific dip in a specific road. So the inundation layer runs at **100 m**.

```
78,000 m ÷ 100 m = 780 columns
72,000 m ÷ 100 m = 720 rows
780 × 720        = 561,600 cells
```

Each cell is 100 m × 100 m = 10,000 m² = **0.01 km²** — about the size of a
couple of city blocks.

### The ratio that explains everything

```
One 0.1° rain cell  ≈ 108 km²
One 100 m flood cell = 0.01 km²

108 ÷ 0.01 = 10,800
```

> **Every single rain value covers roughly 10,800 flood cells.**

Hold that number. It is the whole answer to §4.5.

---

## 4.4 Wards — the unit a control room actually acts on

A **ward** is the smallest municipal administrative unit. It has a councillor, a
budget, a works department and a phone number. **It is the unit at which action
happens.**

- Source: **DataMeet**, `datameet/Municipal_Spatial_Data` →
  `Delhi/Delhi_Wards.geojson`
- **290 polygons**, fields `Ward_Name` / `Ward_No`
- **289 fall inside our AOI box**
- Delhi NCT is ~1,484 km², so the **average ward is ~5 km²** ≈ **500 flood
  cells**

> **A finding worth knowing:** *"MINTO ROAD"* is a **real ward name** in the
> DataMeet file — which means our headline exit gate is directly checkable. ITO
> and Zakhira are **landmarks**, not wards; they sit inside DARYAGANJ and KAROL
> BAGH. The config records this so nobody is misled.

---

## 4.5 THE KEY QUESTION: how do 56 rain values become 289 ward predictions?

**This is the question you flagged, and it is the one a sharp judge will ask.**
Here is the complete answer.

### The apparent problem

> *"You only have 56 rain values across a 78 × 72 km box. Each covers about
> 108 km². An entire ward is 5 km². So within one rain cell, **every ward gets
> the identical rainfall number.** How can you possibly say Minto Bridge floods
> and the ward next door does not?"*

**The premise is completely correct.** Rain is effectively constant across a
0.1° cell. Accept it openly — do not fight it.

### The answer: rain is the trigger, terrain is the discriminator

```
┌──── 1. RAIN: 56 lattice points ────┐    ~11 × 9.75 km cells
│    WHEN and HOW MUCH water arrives │    RainCast / RainFuse / observations
│    Constant across ~10,800 cells   │    ← THE TRIGGER
└──────────────┬─────────────────────┘
               │  each rain cell's value is stamped onto
               │  every 100 m cell inside it
               ▼
┌──── 2. TERRAIN: 561,600 cells at 100 m ────────────────────┐
│    WHERE that water goes                                    │
│    HAND · TWI · slope · plan curvature · flow accumulation  │
│    impervious fraction · built-up · distance-to-drain       │
│    drainage density · sink depth · surface height           │
│    ★ underpass_dist · bridge_dist · underpass_density ★     │
│    ← THE DISCRIMINATOR. All of this varies WITHIN a ward.   │
└──────────────┬──────────────────────────────────────────────┘
               │  InundaNet-v0 combines rain × terrain
               │  per 100 m cell → p_flood
               ▼
┌──── 3. AGGREGATE: 289 wards ──────────────┐
│    models/risk.py rolls cells up to wards │
│    → p_flood, onset, peak, ci90           │
│    → spatial-join exposure                │
│    → risk_score, risk_band                │
└───────────────────────────────────────────┘
```

### Worked example — the sentence to say out loud

> *"Take one 0.1° rain cell over central Delhi. Everything inside it — about
> **10,800 hundred-metre cells** — receives the same 32 mm/hr. But those 10,800
> cells are **not the same place.** One of them is **Minto Bridge**: HAND 2.4 m,
> 73% impervious, and **0 metres** from a below-grade railway underbridge. Another,
> two streets away, sits 6 m higher on an open slope with a drain running past it.
> **InundaNet gives the first one 0.78 and the second 0.04, from the identical
> rainfall input.** The rain says *when*. The terrain says *where*. That
> interaction is precisely what a threshold rule cannot express and what the
> model exists to learn."*

### Three honest caveats — state them before you are asked

1. **We do not claim sub-kilometre rain skill.** We claim sub-kilometre
   *inundation* skill driven by kilometre-scale rain. Those are different claims
   and we only make the second one.
2. **The static terrain does most of the within-event discrimination.** Within a
   single event, rain is nearly constant across a cell, so the cell-level
   ranking comes almost entirely from terrain. Our own numbers separate these:
   **within-event AUC 0.937** (can it rank cells) versus **between-event AUC
   0.973** (can it rank events). *"It learns WHEN more easily than WHERE."*
3. **This is why underpass distance mattered so much.** Once you accept that
   terrain does the discriminating, the quality of your terrain features becomes
   everything — and classical HAND/TWI was failing. See §1.8.

---

## 4.6 CRS and EPSG — why there are two of them

A **CRS** (Coordinate Reference System) is the rulebook for turning positions on
a curved Earth into numbers. **EPSG codes** are just standard IDs for them.

We use exactly two, declared in the config:

```yaml
crs:
  geographic: EPSG:4326     # storage / interchange
  projected:  EPSG:32643    # UTM 43N — metric operations
```

| | **EPSG:4326** (WGS84) | **EPSG:32643** (UTM zone 43N) |
|---|---|---|
| Units | **degrees** | **metres** |
| Good for | storing points, GeoJSON, web maps | **distance, area, building a 100 m grid** |
| Bad for | measuring anything — a degree is not a fixed distance | spanning wide east-west areas |

**Why you need both:** you cannot build a *100 metre* grid in degrees, because a
degree is not a fixed number of metres. So all metric work happens in
**EPSG:32643** and results are converted back to **EPSG:4326** for the map.

> **⚠️ The silent killer.** CRS misalignment is the #1 source of geospatial bugs.
> Two rasters at different resolutions in different projections will happily
> "align" to garbage without ever raising an error. The mitigation in this repo:
> **one CRS and one 100 m transform defined in `cube/grid.py`, everything derived
> from it, and alignment asserted after every resample.** All eleven `g100_*.tif`
> layers were verified byte-identical after a full rebuild.

---

## 4.7 🎤 JUDGE QUESTIONS — spatial resolution

**"You have 56 rain points. How can you claim ward-level output?"**
> We do not claim ward-level *rain*. We claim ward-level *inundation*. The rain
> lattice tells us **when and how much** water arrives — that is a broad-scale
> phenomenon and 0.1 degree is the native resolution of the data. Then a hundred
> metre terrain grid, 561,600 cells with fourteen physical features each, decides
> **where that water goes.** One rain cell covers about 10,800 flood cells, and
> those cells differ by up to fifteen metres of elevation, by a factor of four in
> imperviousness, and by two and a half kilometres in distance to the nearest
> underpass. **The rain is the trigger; the terrain is the discriminator.**

**"Why 0.1 degree and not finer? Could you not downscale?"**
> Because 0.1 degree is the **native resolution of the source**. IMERG is
> published at 0.1 degree, ERA5-Land is about nine kilometres. Making a finer
> lattice would interpolate the same numbers into more boxes and manufacture an
> impression of detail that is not in the data. We would rather be honest about
> the rain resolution and put our resolution where it is real — in the terrain.

**"Within one rain cell, every ward gets the same rainfall. So is the ward
ranking just a static map?"**
> Within a single event, largely yes — and **we measured exactly that** rather
> than glossing it. Our within-event AUC is 0.937 and our between-event AUC is
> 0.973, and the gap is the honest statement that the model learns **when** more
> easily than **where**. What stops it from being *merely* a static map is that
> the static component is genuinely predictive and genuinely learned: on
> imperviousness-matched negatives the model scores 0.918 while the naive "is this
> urban" shortcut scores 0.564. And the rain component is not decoration — we
> forced monotonic constraints so that flood probability can never fall as rain
> rises, and we verified the response curve directly.

---
---

# PART 5 — THE FUSION CUBE

---

## 5.1 What it is — with a real worked example row

**The one-sentence mental model:**

> **The cube is a spreadsheet. Each row is one place at one moment. The columns
> are everything every source knows about that place-moment. One column is the
> answer.**

**"Fusion" literally just means: all the source families sit in the same row.**
That is the entire trick. Because the columns are adjacent, a model can learn
*"when GFS and ECMWF disagree AND CAPE is high, trust the observations more."*
It can only learn that if the columns are side by side.

### The actual file

```
cube/ncr_cube.parquet     3,623,424 rows × 28 columns, 47 MB
                          56 lattice points × 64,704 hours
                          2018-05-15 → 2025-09-30
```

> **A naming honesty note:** the charter planned an xarray/zarr multidimensional
> store, hence the word "cube." What was actually built is a **flat Parquet
> table**. Parquet is a compressed columnar file format — fast to read, small on
> disk. If a judge asks "is it a real data cube?", the honest answer is: *"It is a
> tidy long-format table with the same content. We chose flat over
> multidimensional because every consumer is a gradient-boosting model that wants
> rows, not because we could not build the array."*

### A worked example row

| column | value | where it came from |
|---|---|---|
| `valid_time` | `2024-06-28 01:00:00+00` | the hour this row is **about** |
| `issue_time` | `2024-06-28 01:00:00+00` | when this became **knowable** |
| `lat` / `lon` | `28.65` / `77.20` | central Delhi lattice point |
| `precip_obs` | `32.9` | **← THE ANSWER.** ERA5-Land (A1) |
| `temp_2m` | `27.4` | ERA5-Land |
| `rh` | `96` | ERA5-Land |
| `soil_moisture_0_7cm` | `0.41` | ERA5-Land — saturated soil floods faster |
| `cape` | `3990` | A2 historical-forecast (NOT A1 — see below) |
| `convective_inhibition` | `-12` | A2 bonus feature |
| `lifted_index` | `-4.2` | A2 bonus feature |
| `gfs_precip` | `18.1` | A2, NOAA GFS, at this lead |
| `ecmwf_precip` | `24.6` | A2, ECMWF IFS |
| `icon_precip` | `11.3` | A2, DWD ICON |
| `nwp_n_models` | `3` | **how many models actually spoke** |
| `nwp_disagreement` | `13.3` | pairwise spread — *disagreement predicts uncertainty* |
| `nwp_issue_time` | `2024-06-28 06:00:00+00` | **gated separately** — see §5.3 |
| `imd_rain_daily` | `150.7` | A11 IMD gridded (daily, coarse→fine crosswalk) |
| `static_hand` | `2.39` | Copernicus DEM → pysheds |
| `static_impervious` | `0.731` | ESA WorldCover class 50 |
| `split` | `val` | 2024 → validation |

### The CAPE story — why one column sits in the "wrong" place

`cape` is an atmospheric instability measure (**Convective Available Potential
Energy**, J/kg). High CAPE means thunderstorms can build. It should logically
come from A1 with the rest of the observations.

**It does not, and here is why.** When A1 was probed, `cape` came back
**100% NULL — 64,704 out of 64,704 rows, dtype `object`** — on *every* model
variant. CAPE is an ERA5 **single-levels** field, not an ERA5-**Land** one.

> **Written blind, RainCast would have trained on a dead column and nobody would
> have noticed.**

**The resolution turned out to be architecturally better.** CAPE is sourced from
**A2** (`historical-forecast-api`), which serves it fully populated — **3,990
J/kg** during the 28 June 2024 window — plus two instability features we had not
planned for, `convective_inhibition` and `lifted_index`. And because A2 rows
carry a real `issue_time`, those instability features obey the no-look-ahead law
**for free.**

---

## 5.2 `issue_time` vs `valid_time` — the single most important idea

Every forecast record carries **two** timestamps. Get this straight and you can
answer the hardest question a judge will ask.

| | Meaning | Example |
|---|---|---|
| **`valid_time`** | The moment the forecast is **about** | "9 a.m. Tuesday" |
| **`issue_time`** | The moment the forecast was **produced / became available** | "6 a.m. Tuesday" |
| **Lead time** | `valid_time − issue_time` | 3 hours |

### Why this is not bureaucracy

Imagine training a model to predict 9 a.m. rain, and one of your feature columns
happens to be *the forecast that was made at 8:55 a.m.* Your model will score
brilliantly. It is also **completely useless**, because at 6 a.m. — when you
actually need the warning — that column does not exist yet.

That is **look-ahead leakage**, and it is how most ML projects secretly fail. It
does not throw an error. It does not look wrong. It just produces a number that
evaporates in production.

> **🎤 The line:** *"Every forecast row in our cube carries both when it was
> issued and what time it is about. That single design decision is the difference
> between a model that works and a model that scores well because it peeked."*

---

## 5.3 The no-look-ahead law, and the bug it caught

### The law

> There is **exactly one read path** into the cube: **`cube.at(t0)`**. It returns
> only rows where `issue_time <= t0`. Nothing else is permitted to read the data.

Then `eval/leakage_tests.py` **shuffles and corrupts every future row and asserts
the features at `t0` are unchanged.** Six sub-tests. It runs in `make preflight`.

### The bug it caught — tell this story, it is your best credibility moment

The very first time the suite ran, **it failed its own guard test.**

`issue_time` equalled `valid_time` on **every single row** — because A2's real
`issue_time` had been silently dropped during a merge. Which meant:

> **The accessor was filtering on nothing, and the other five tests were passing
> VACUOUSLY — they looked green while testing air.**

**The fix — per-column NWP gating.** Observation rows are knowable at their own
valid time, but an NWP run is not. So NWP columns get their own stamp:

```
nwp_issue_time = valid_time.normalize() + 6 hours
```

**Deliberately conservative.** A 00Z global run is not on the wire until roughly
05–06Z. Being conservative can only *cost* us skill; being optimistic
**manufactures** it. Plus per-lead stamps for `previous_day1/2/3`.

`accessor.at()` now **blanks NWP cells** whose run was not yet issued, while
keeping the observation row visible. Suite now **6/6 PASS**, and the guard proves
the gating *bites* — **280 future-issued NWP cells blanked at `t0`**.

> **🎤 The lesson, and it is a great line:** *"A leakage test that cannot fail is
> worse than no leakage test. Ours failed on day one, and that is why we trust it
> now."*

---

## 5.4 The splits — why by year and never random

```
TRAIN   2.76 M rows   ≤ 2023    ← the model learns here
VAL       492 k rows    2024     ← isotonic calibration fitted HERE AND ONLY HERE
TEST      367 k rows    2025     ← never seen. All reported scores come from here.
```

### Why never random

> Adjacent grid cells and adjacent hours are **strongly autocorrelated.** A
> random split puts near-duplicates of a test row into training. The model
> "predicts" 15:00 by having memorised 14:00. **Every score inflates and the
> skill is zero.**

Splitting by **event and by year** is the only honest option on this kind of
data. That is charter rule **R5**.

### The extra guard for InundaNet: 5 km spatial-block CV

Same problem in space. Two 100 m cells 200 m apart are nearly the same place.
So InundaNet uses **`GroupKFold` with 5 km spatial blocks as the groups** — an
entire 5 km block is either wholly in training or wholly in validation, never
split across both.

### Where the splits differ per model — and why

| Model | Train | Val | Test | Why |
|---|---|---|---|---|
| **RainCast** | ≤2023 | 2024 | **2025** | ERA5 runs to 2025, so a normal split works |
| **RainFuse** | ≤2022 | 2023 | **2024** | **IMD gridded stops at 2024.** A 2025 test split is *literally empty* — the first run correctly produced 0 test positives and refused to score |
| **InundaNet** | 5 km spatial-block CV | | | Space, not time, is the correlation risk |

> **The RainFuse split is a bonus, not a compromise:** it puts the **28 June 2024
> demo event in the held-out test year** — the strongest possible place to demo
> from. Say that out loud.

---

## 5.5 The three derived tables

The cube is raw. Three specialised tables are built from it, one per model:

| Table | Shape | Feeds |
|---|---|---|
| `cube/raincast_table.parquet` | **1.31 M rows × 100 cols**, monsoon months only | RainCast-v0 |
| `cube/rainfuse_table.parquet` | **1.36 M rows**, wide NW-India domain | RainFuse-v0 |
| `data/labels/inunda_labels_v2.parquet` | **120 k cell-events** | InundaNet-v0 |
| `cube/raincast_table_imerg.parquet` | 1.31 M rows + 24 IMERG cols | the A/B experiment (not shipped) |

---

## 5.6 🎤 JUDGE QUESTIONS — leakage

**"How do I know there is no data leakage?"** *(the hardest technical question
you will get — memorise this)*
> Four layers. **One:** every forecast row stores both `issue_time` and
> `valid_time`. **Two:** the cube has exactly **one read path**, `cube.at(t0)`,
> which returns only data issued at or before t0 — there is no second way to read
> it. **Three:** an automated suite shuffles and corrupts every future row and
> asserts the features at t0 are unchanged; it runs in our preflight gate.
> **Four:** splits are by event and by year, never random, because adjacent cells
> and adjacent hours are autocorrelated and a random split would inflate every
> score. And I can tell you the test works, because **it failed the first time we
> ran it** — `issue_time` equalled `valid_time` everywhere, so the filter was
> doing nothing and the other five tests were passing vacuously. We found that,
> fixed it with conservative per-column NWP gating, and it now demonstrably blanks
> 280 future-issued cells at t0.

**"Your NWP gating adds six hours. Isn't that arbitrary?"**
> It is deliberately conservative, and the direction of the bias is the point. A
> 00Z global run is not actually on the wire until roughly 05 or 06Z, so six
> hours is realistic rather than arbitrary. And critically: **being conservative
> can only cost us skill. Being optimistic would manufacture it.** If we are
> wrong, we are wrong in the direction that understates our own performance.

**"Why does RainFuse use a different test year from RainCast?"**
> Because its truth layer is IMD gridded, which is unpublished beyond 2024. A
> 2025 test split is literally empty — our first run produced zero test positives
> in all three categories and correctly refused to score rather than reporting a
> number. So RainFuse trains to 2022, validates on 2023 and tests on 2024. The
> useful side effect is that our flagship demo event, 28 June 2024, now sits in
> the held-out year.

---
---

# PART 6 — THE MODELS

---

## 6.1 Data provenance — exactly what feeds each model

**This is the table you asked for. Every model, every input, every exact source.**

### RainCast-v0 — the 0–6 h nowcast

| | |
|---|---|
| **Training table** | `cube/raincast_table.parquet` — 1.31 M rows × 100 cols, monsoon months only |
| **TARGET (the answer)** | `precip_obs` from **ERA5-Land hourly**, source **A1**, via `archive-api.open-meteo.com/v1/archive` |
| **Feature family: observations** | ERA5-Land lags at 1/2/3/6 h, accumulations 3/6/24 h, antecedent 3/7/15-day rain, API. Source **A1** |
| **Feature family: advection** | 18 columns — 8-neighbour rain at t..t-3, N/S/E/W directional means, signed NS/EW gradients, box mean/max. **Derived from A1**, not a new source |
| **Feature family: NWP** | ECMWF IFS + NOAA GFS + DWD ICON precipitation at lead, pairwise disagreement, `nwp_n_models`, plus CAPE / convective inhibition / lifted index. Source **A2**, `historical-forecast-api.open-meteo.com` |
| **Feature family: static** | HAND, TWI, slope, impervious, distance-to-drain at the lattice point. Sources **A7** (Copernicus DEM) + **A5** (ESA WorldCover) + **A9** (OSM) |
| **Feature family: time** | hour-of-day and day-of-year **cyclical encodings** (sin/cos) |
| **Feature count used** | **52** (after an 80% train-coverage filter, computed on TRAIN only) |
| **Test split** | **2025** |

### RainFuse-v0 — the 6–72 h NWP correction

| | |
|---|---|
| **Training table** | `cube/rainfuse_table.parquet` — 1.36 M rows |
| **Domain** | **WIDE: NW India, 70–84 °E, 21–33 °N** — 195 NWP points × **2,793 IMD cells**. *Not Delhi-only* |
| **TARGET (the answer)** | **IMD gridded 0.25° daily rainfall**, source **A11**, via the `imdlib` package. **Gauge-based, and it captures the extreme** |
| **Features** | 3-model precipitation at lead indexed by `issue_time`, **pairwise disagreement**, ERA5 climatological anomaly, last-24 h accumulation, terrain, monsoon-phase + time encodings, 3×3 NWP neighbourhood means. Sources **A2w** + **A1** |
| **Heads** | Binary exceedance at IMD's **official** categories: **64.5 / 115.6 / 204.5 mm** |
| **Test split** | **2024** (IMD gridded stops there) |

### InundaNet-v0 — rain to water on the ground

| | |
|---|---|
| **Training table** | `data/labels/inunda_labels_v2.parquet` — **120,330 cell-events**, 8,595 positive (base rate 7.1%) |
| **TARGET (the answer)** | **Hand-built label set** — 84 curated Delhi waterlogging points (10 high-confidence, 74 medium) from **Delhi PWD + Delhi Traffic Police published lists + timestamped news reports**, buffered to 200 m, stamped with event windows |
| **Static features** | HAND, TWI, slope, plan curvature, flow accumulation, sink depth, surface height, distance-to-drain, drainage density (**A7** Copernicus DEM → `pysheds`); impervious fraction (**A5** ESA WorldCover class 50); built-up (**A5** GHSL GHS-BUILT-S); **★ `underpass_dist`, `bridge_dist`, `underpass_density` (A9 OSM `tunnel=yes` / `layer<0`) ★** |
| **Dynamic features** | `rain_sum`, rain accumulations 1/3/6/24 h from the cube; antecedent precipitation index; ERA5 soil moisture |
| **Negatives** | Cells >1 km from any positive **within the same event window**, PLUS **25,785 dry-day negatives** on the *same cells* on dry monsoon days |
| **Feature count** | **17** |
| **Validation** | **GroupKFold, 5-fold, on 5 km spatial blocks** (256 blocks) |
| **Exposure join** | **GHS-POP R2023A** 100 m population + **OSM** hospitals/schools/pumps + **DataMeet** ward polygons → `data/static/exposure.parquet` |

### Explicitly BLACKLISTED features (and why) — InundaNet

| Excluded | Why |
|---|---|
| `point_rain_mm`, `sample_weight`, `rain_confirmed`, `point_id`, `point_name` | **Computed during labelling** — functions of the answer. Leakage |
| `lat`, `lon`, `x_utm`, `y_utm`, `cell_id`, `row`, `col` | With 84 points, coordinates let a tree **memorise blackspot locations** and score beautifully while learning nothing transferable |

A **null-rate tripwire** now runs over every surviving feature — because
`point_id` was originally excluded only *by accident* (strings dropped by a
numeric filter). **Luck, not methodology.** Now it is methodology.

---

## 6.2 What LightGBM actually is

### Step 1 — a decision tree is a flowchart

```
                  Is rain in the last hour > 3 mm?
                    ┌───── yes ─────┐   ┌──── no ────┐
             Is CAPE > 1500?              Is 24h accumulation > 40 mm?
          ┌── yes ──┐  ┌── no ──┐       ┌── yes ──┐  ┌── no ──┐
        predict      predict            predict     predict
         0.71         0.22               0.19        0.01
```

That is it. A tree is a series of yes/no questions ending in a number. A computer
"learns" a tree by trying every possible split on every feature and keeping the
one that separates the outcome best.

**Why trees are perfect for this problem:** a tree naturally expresses
**interactions**. *"Low HAND AND high impervious AND near an underpass"* is three
splits down one branch. That is literally the physical statement in §1.8 — *50 mm
on a sealed low-lying cell floods, uphill it does not* — and it is exactly what a
linear model **cannot** express.

### Step 2 — gradient boosting is building trees on top of mistakes

One tree is weak. So:

```
Tree 1   makes a rough prediction                          → it is wrong by some amount
Tree 2   is trained to predict TREE 1'S ERRORS             → add it in
Tree 3   is trained to predict the REMAINING errors        → add it in
   ...
Tree 500 fixes what 499 trees still could not              → add it in

FINAL PREDICTION = tree1 + tree2 + tree3 + ... + tree500   (each scaled by 0.05)
```

**The plain analogy:** one expert makes a guess. A second expert only studies
where the first was wrong. A third studies where the first two were *still*
wrong. Five hundred specialists in each other's blind spots. That is boosting.

### Step 3 — the actual maths, if a judge pushes

The "gradient" is not a metaphor. At each round, the new tree is fitted to the
**negative gradient of the loss function** with respect to the current
predictions.

For binary classification we use **log-loss**:
```
L = −[ y·log(p) + (1−y)·log(1−p) ]
```
Its gradient with respect to the raw score, for the logistic link, is beautifully
simple:
```
∂L/∂F  =  p − y
```
**That is literally "predicted minus actual" — how wrong we were and in which
direction.** So each new tree is trained to predict the current residual error.
Prediction is updated as:
```
F_new = F_old + η · h(x)          where η = 0.05 (our learning rate)
```
and the final probability comes back through the sigmoid `p = 1/(1+e^(−F))`.

**Why the learning rate 0.05?** Each tree is only allowed to move the prediction
5% of the way towards fixing the error. Small steps, many of them — this is
**shrinkage**, and it is the main regulariser in boosting. Big steps overfit.

### Step 4 — what "Light" means

LightGBM's specific innovations over classic gradient boosting:

| Innovation | What it does | Why we care |
|---|---|---|
| **Histogram binning** | Buckets each continuous feature into 255 bins instead of testing every unique value | Massive speedup — training in seconds on CPU |
| **Leaf-wise growth** | Grows the leaf with the **biggest loss reduction**, rather than growing level-by-level | Deeper, more accurate trees for the same leaf budget |
| **GOSS** | Gradient-based One-Side Sampling — keeps all high-gradient (badly-predicted) rows, subsamples the easy ones | Speed without losing the hard cases |
| **EFB** | Exclusive Feature Bundling — merges mutually-exclusive sparse features | Fewer effective columns |
| **★ Native NaN handling ★** | Missing values are **routed down a learned default branch**, not imputed | **This one is load-bearing for us — see below** |
| **★ Monotonic constraints ★** | Forces the output to be non-decreasing in a chosen feature | **Also load-bearing — see §6.6** |

### Our exact hyperparameters

| | RainCast | RainFuse | InundaNet |
|---|---|---|---|
| `objective` | `binary` | `binary` | `binary` |
| `learning_rate` | 0.05 | 0.05 | 0.05 |
| `num_leaves` | **63** | **63** | **31** |
| `feature_fraction` | 0.8 | 0.8 | 0.8 |
| `bagging_fraction` / `freq` | 0.8 / 1 | 0.8 / 1 | 0.8 / 1 |
| `min_data_in_leaf` | 50 | 50 | **100** |
| `num_boost_round` | **500** | **600** | **400** + early stopping (40) |
| `monotone_constraints` | — | — | **+1 on every rain feature** |

**Why `num_leaves` is lower for InundaNet (31 vs 63):** fewer training rows
(120 k vs 1.31 M) and only 17 features. A more complex tree would memorise 84
label locations. `min_data_in_leaf=100` pushes the same way.

**Why `scale_pos_weight` was DROPPED:** RainCast originally used balanced class
weights. It **fought the isotonic calibration and inflated FAR.** Removing it
improved both. A real, measured decision — not a default.

---

## 6.3 Why LightGBM and not something else

### The model ladder — climb it only on evidence

```
persistence  →  pySTEPS  →  gradient boosting  →  deep networks
 (free)        (no training)     (LightGBM)      (SmaAt-UNet / ConvLSTM)
                                    ▲
                              WE ARE HERE
```

**You do not skip rungs.** You climb only when the rung below has been measured
and beaten. That principle *is* the answer to "why not deep learning."

### Why LightGBM specifically — six concrete reasons

| # | Reason | Why it is load-bearing *for this project* |
|---|---|---|
| 1 | **Native NaN handling** | Our NWP coverage is genuinely incomplete: **GFS from Mar 2021, ICON from Nov 2022, ECMWF only from Feb 2024.** LightGBM routes NaN down a learned branch rather than forcing us to impute. We keep columns NaN and add `nwp_n_models` so the model can learn *to trust the spread only when the spread is real* |
| 2 | **Monotonic constraints** | **We needed p_flood to never fall as rain rises.** LightGBM supports `monotone_constraints` natively. Without it the replay showed flood risk *dropping* mid-cloudburst |
| 3 | **Speed on CPU** | Trains in seconds. **Nothing in v0 needs a GPU** — the bottleneck is data wrangling, not compute |
| 4 | **Exact explainability** | **TreeSHAP** gives mathematically exact per-prediction attributions for tree ensembles. That is how "78%" becomes *"because it is next to an underpass."* Saliency maps on a neural net are not exact and judges rightly distrust them |
| 5 | **Natively probabilistic** | `objective=binary` outputs a probability directly, which is what a calibrated warning system needs |
| 6 | **Trees dominate tabular data** | On heterogeneous tabular data at this scale, gradient-boosted trees beat neural networks. This is a well-established empirical result, not a preference |

### Could we have used something else? Honest answers

| Alternative | Verdict |
|---|---|
| **XGBoost** | **Yes — near-identical results.** Same algorithm family. LightGBM is faster and has cleaner leaf-wise growth. No meaningful accuracy difference expected |
| **CatBoost** | Yes. Its edge is ordered boosting and native categorical handling. **We have almost no categorical features**, so its advantage does not apply here |
| **Random Forest** | **Worse.** Bagging without boosting, no monotonic constraints in scikit-learn, and it does not sharpen residuals |
| **Logistic regression** | Interpretable but **cannot express the core physical statement** — "low HAND AND impervious AND near underpass" is an interaction, and a linear model has none unless you hand-craft every product term |
| **SmaAt-UNet / ConvLSTM** | **The right answer — after radar decoding.** These consume *sequences of images*. We have no decoded radar frames, so there is nothing to convolve over. Scheduled for the radar era, where they actually pay off |
| **Transformers / foundation models** (GraphCast, Pangu, FourCastNet) | Genuinely state-of-the-art for **global medium-range** forecasting. Wrong tool here: they are global-scale, need enormous compute, and do not address the 0–6 h urban nowcast or inundation at all |

> **🎤 The line:** *"Model ladder by evidence: persistence, then pySTEPS, then
> gradient boosting, then deep nets. On this data volume and this timeline,
> boosted trees beat a half-trained U-Net, run in seconds on CPU, and explain
> themselves via exact TreeSHAP. Deep nowcasting nets consume radar image
> sequences — we do not have decoded radar, so there is literally nothing for a
> convolution to operate on. They are scheduled for the radar era, where they
> pay off."*

---

## 6.4 RainCast-v0 — the 0–6 h nowcast

### The intuition

**Persistence-with-correction.** Rain that has been intensifying for two hours
under high CAPE usually keeps going. The neighbour columns tell us where the
existing rain is drifting. **RainCast learns when to trust that extrapolation and
when the atmosphere says otherwise.**

### What is a "head"? — literally a separate model file

You asked this directly. In this codebase a head is **not** an architectural
concept — it is a **separate trained LightGBM model on disk.** Go look:

```
models/raincast_v0_p5_w1.txt        ← a head
models/raincast_v0_p5_w3.txt        ← a head
models/raincast_v0_acc10_w6.txt     ← a head
...  12 files = 12 heads = 12 independent models
```

The term comes from neural networks (one shared body, several output heads).
Here they are 12 fully independent boosters that share a feature table.

**Why not one model?** Because *"will it rain a lot?"* is not one question. A
duty officer needs *"will any hour spike?"* and *"how much total water?"* over
*1, 3 or 6 hours*. Different questions need different models.

### Decoding `p5_w1`, `acc10_w6` — the naming scheme

**Two parts: question type + window.**

| Prefix | The question |
|---|---|
| `p5` | Will **any single hour** in the window exceed **5 mm/hr**? (`p` = peak) |
| `p10` | Will any single hour exceed **10 mm/hr**? |
| `acc10` | Will the **total accumulation** over the window exceed **10 mm**? |
| `acc20` | Will the total exceed **20 mm**? |

| Suffix | The window |
|---|---|
| `w1` | the next **1 hour** |
| `w3` | the next **3 hours** |
| `w6` | the next **6 hours** |

**So:**
- **`p5_w3`** = *"Will any hour in the next 3 hours exceed 5 mm/hr?"*
- **`acc10_w6`** = *"Will the next 6 hours total more than 10 mm?"*

**4 question types × 3 windows = 12 heads.**

> ⚠️ **Legacy naming trap — know this.** The field names in the output JSON are
> `p15` and `p50`, inherited from the charter's original 15 mm and 50 mm
> thresholds. **Our heads are actually 5 mm and 10 mm, ERA5-scale.** The
> precompute step now writes an explicit `head_thresholds_mm` block declaring
> this, and the UI reads it rather than hardcoding. **If a judge reads "p15",
> correct them before they catch it.**

### The two redesigns that saved this model

**Redesign 1 — the target reframe.**
v1 asked *"does hour t+lead exceed 5 mm?"* Result: **CSI 0.01–0.06, FAR > 0.98.**
Effectively dead. Two faults:
- **Statistically**, a specific single future hour at a specific 0.1° point is a
  **0.9% event**, and the exact *hour* a convective cell fires is near-unpredictable.
- **Operationally**, nobody warns *"it will rain between 04:00 and 05:00."*

Reframed to **window heads**: will *any* hour in t+1..t+W exceed, and what is the
*accumulation*. Positives went **1,516 → 4,136 (w3) / 7,793 (w6)**. CSI roughly
doubled.

**Redesign 2 — advection features.**
v2 still modelled each lattice point **in isolation**, so a storm 11 km upwind was
**invisible**. Added **18 neighbour columns**: 8-neighbour rain at t..t-3, N/S/E/W
directional means, signed NS/EW gradients (drift direction), box mean/max.

> This is the physical content of the pySTEPS optical-flow baseline, **expressed
> as tree-splittable features.**

Result: `p5_w1` CSI **0.060 → 0.104**; `p5_w6` **0.070 → 0.104**; **FAR 0.98 → 0.82.**

**Both redesigns obeyed the charter gate's own instruction: *"if not met, ADD
FEATURES, never add model complexity."*** Say that — it shows discipline.

### The scores (TEST 2025)

| head | test pos | **CSI** | POD | FAR | persistence | raw GFS | beats both? |
|---|---:|---:|---:|---:|---:|---:|:--:|
| `p5_w1` | 1,516 | **0.130** | 0.253 | 0.790 | 0.068 | 0.009 | ✅ |
| `p5_w3` | 4,136 | 0.121 | 0.213 | 0.783 | 0.049 | 0.015 | ✅ |
| `p5_w6` | 7,793 | 0.118 | 0.230 | 0.805 | 0.039 | 0.014 | ✅ |
| **`acc10_w6`** | 5,272 | **0.144** | 0.274 | 0.766 | 0.071 | 0.101 | ✅ |
| `acc10_w3` | 1,826 | 0.086 | 0.342 | 0.897 | 0.044 | 0.042 | ✅ |
| `p10_w6` | 1,528 | 0.025 | 0.065 | 0.960 | 0.015 | 0.000 | ✅ |
| `acc20_w1` | **22** | 0.030 | 0.227 | 0.967 | 0.073 | 0.000 | ❌ |
| `acc20_w6` | 742 | 0.034 | 0.097 | 0.951 | 0.029 | 0.043 | ❌ |

**10 of 12 heads beat BOTH baselines.** Two fail and are reported as failures.

**Reading row 1 in plain English:**
> *"Over the 2025 monsoon there were 1,516 hours where rain exceeded 5 mm at a
> lattice point. We caught 25% of them. Of every 100 warnings we issued, 79 were
> wrong. Our balanced score is 0.130 — nearly **2× better** than assuming the
> current weather continues, and **14× better** than the US government's global
> physics model."*

**Best head is `acc10_w6` (0.144)** — longer window, accumulation question, more
positives, smoother target, and operationally the most useful question.

**`acc20_w1` has only 22 test positives** and should be suppressed — the
min-positives guard was set at 20 and is too loose. Noted honestly.

---

## 6.5 RainFuse-v0 — the 6–72 h NWP correction

### The intuition

**Where physics is systematically wrong.** ECMWF, GFS and ICON each over- or
under-predict in **learnable situations**, and **their disagreement itself
predicts uncertainty.**

> **RainFuse never replaces the physics — it corrects and calibrates it.**

### Why this is the most defensible ML claim in the pitch

This is exactly what operational meteorology has called **Model Output Statistics
(MOS)** since the 1970s, done with modern tooling. **No meteorologist will argue
with it.** You are not claiming to out-forecast ECMWF; you are claiming to
de-bias it, which is standard, respected practice.

### Why the thresholds are 64.5 / 115.6 / 204.5 mm

**Because they are IMD's own official 24-hour categories:**

| mm (24 h) | IMD category |
|---|---|
| 64.5 | **Heavy** |
| 115.6 | **Very heavy** |
| 204.5 | **Extremely heavy** |

Using IMD's thresholds instead of invented ones means our output maps **directly**
onto IMD's own warning language. In front of IMD judges that is a significant
deliberate choice, not a coincidence. **Say it.**

### The scores (TEST 2024)

| category | test pos | CSI | raw NWP CSI | **Brier** | raw NWP Brier |
|---|---:|---:|---:|---:|---:|
| **heavy** 64.5 mm | 4,066 | 0.090 | 0.080 | **0.0112** | 0.0401 |
| **very heavy** 115.6 mm | 834 | 0.021 | **0.039** ❌ | 0.0025 | 0.0146 |
| extremely heavy 204.5 mm | **72** | *skipped — below the min-100 guard* | | | |

### The honest headline

> **RainFuse does not detect many more heavy-rain days than the physics does. It
> makes the physics' probabilities MEAN something. Brier 0.0112 versus 0.0401 —
> 3.6× better calibrated.**

**The analogy to use:** two doctors. Doctor A and Doctor B identify sick patients
about equally well. But when A says *"70% chance"*, it happens 70% of the time,
while B says *"70%"* for things that happen 20% of the time. **A's number is
actionable. B's is noise.** That is the entire value of calibration, and it is
Proof P-2.

**`very_heavy` loses on CSI (0.021 vs 0.039)** while winning on Brier. **Reported
as a FAIL, not spun.**

### One more leak found and fixed here

Climatology was originally computed with a `groupby`-transform over the **whole
table**, which folded **test-year observed rainfall into a training feature.**
Now computed on **training years only.** Third leak caught in this project.

---

## 6.6 InundaNet-v0 — rain to water on the ground

### The intuition

**The interaction a threshold rule cannot express.** 50 mm on a low-HAND,
high-impervious cell far from a drain with saturated soil floods; the same 50 mm
two streets uphill does not.

### Is InundaNet "just a static ML model, nothing great"?

**Straight answer: the algorithm is ordinary. Everything around it is not.**

- **It is the only model that answers the actual problem statement.** RainCast
  and RainFuse predict millimetres. Only InundaNet converts millimetres into
  water on the ground and then into people affected. **That conversion is the
  USP.**
- **It is not static.** `rain_sum` is the **#1 feature** by gain (35,059), and
  monotonic constraints force the response to rise with rain. It was *made*
  dynamic — see fix 4 below.
- **The intellectual content is in the features and the labels, not the
  algorithm.** Which is normal in applied ML and worth saying plainly.

### The five corrections — the credibility story

This is the best "we did real science" narrative you have. Learn all five.

**1 · LABEL-PROCESS LEAKAGE.**
First run: **AUC-PR 0.9104**, within-event ROC-AUC 0.9653. Beautiful — and
**impossible**, given that two independent measurements had already shown terrain
does *not* explain these labels. Top feature was `point_rain_mm` by 2×. Audit
against the label column: `point_id`/`point_name` **100% null for negatives, 0%
null for positives**; `sample_weight` exactly 1.0 vs 0.637; `rain_confirmed`
0.878 vs 0.574. All computed *during* labelling — functions of the answer.
**After blacklisting: AUC-PR 0.5454.** A 0.36 drop, taken honestly.

**2 · COORDINATES EXCLUDED BY DESIGN.**
With 84 labelled points and negatives sampled >1 km away, raw `lat`/`lon` let a
tree memorise *"near a known blackspot"* and score beautifully while learning
nothing transferable.

**3 · NEGATIVE-SAMPLING BIAS — the subtlest and most important.**
Negatives drawn >1 km from positives are systematically **less urban**
(impervious **0.244 vs 0.827**; built-up 0.105 vs 0.378). **Imperviousness ALONE
scored ROC-AUC 0.867.** So a model could look excellent having learned only *"is
this cell urban?"* — the classic **presence-only artifact**.
Fix: re-score on **imperviousness-matched negatives**. On that harder set the
urban shortcut collapses to **0.564** while the model holds **0.918**.
**That matched number is the one to quote — not the flattering 0.93.**

**4 · THE MODEL IGNORED RAIN.**
Discovered by testing the model's **rain response directly** rather than trusting
CV scores. Hold a median urban cell fixed and sweep rainfall: p_flood went
**0.0041 at 0 mm → 0.0052 at 200 mm. FLAT.**
> **A flood model that ignores rain is not a flood model, whatever its AUC says.**

Root cause: every negative was drawn from the **same event windows** as the
positives, spatially >1 km away but temporally identical. So within each pair the
rainfall was nearly the same, rain had **zero power to separate the classes**, and
the model correctly concluded rain was uninformative.

Fix — **dry-day negatives** (`features/dry_negatives.py`): **25,785 negatives on
the SAME cells on dry monsoon days.** The contrast becomes *"same place + heavy
rain = flooded / same place + no rain = dry"*, which terrain cannot explain away.
`rain_sum` jumped to **top feature** (gain 8,612 → 42,548). Between-event ROC-AUC
went from **nan → 0.974**. **Side benefit:** it also kills the urban/rural
sampling artifact, because a dry-day negative has *identical* imperviousness to
its own positive.

**5 · MONOTONIC CONSTRAINTS.**
Response was still wobbly — it dipped between 50 and 80 mm — so the replay showed
flood risk **falling as the cloudburst peaked.** Applied
`monotone_constraints = +1` on all rain features (terrain left unconstrained at 0,
because terrain effects genuinely can go either way).
Response became **0.0004 → 0.0054, never decreasing.** Cost **AUC-PR 0.567 →
0.498.**
> **Taken anyway, because a screen showing risk dropping mid-cloudburst is
> indefensible no matter what CV says.**

### Then the breakthrough — the drainage crack

Covered fully in §1.8. Summary: OSM `tunnel=yes` / `layer<0` → 1,305 below-grade
ways → `underpass_dist` becomes the **#2 feature** → **AUC-PR 0.498 → 0.611**,
matched-negative ROC-AUC **0.829 → 0.918**, lift over HAND **8.0× → 9.8×**.

### Final scores

```
n_rows            120,330    (8,595 positive, base rate 7.1%)
AUC-PR              0.611    ← 8.6× random; HAND-only baseline 0.062 → 9.8× lift
ROC-AUC             0.954
within-event AUC    0.937    ← can it rank CELLS (the "where")
between-event AUC   0.973    ← can it rank EVENTS (the "when")
matched-negative    0.918    ← vs 0.564 for the imperviousness shortcut
CV                  GroupKFold 5-fold on 5 km spatial blocks (256 blocks)
```

**Top features by gain:**
```
1. rain_sum             35,059     ← the trigger
2. st_underpass_dist    34,593     ← the drainage proxy  ★
3. st_bridge_dist       31,284
4. st_built_up          24,791
5. st_surface_height    12,875
6. st_impervious        12,740
7. st_dist_drain        11,184
8. st_slope              8,679
9. st_sink_depth         7,498
10. st_hand              7,381     ← the classical predictor, only #10
```

> **Note what that list says:** the top drivers are **pluvial/urban**, NOT the
> classical HAND/TWI terrain stack. **HAND is only #10.** That is fully
> consistent with everything Phase 2 found, and it is a real finding worth
> presenting.

### The impact engine — deterministic, and we say so

```
flooded cells × exposure  →  people (GHS-POP)
                             hospitals / schools (OSM)
                             road-km
                             pumps

risk_score = probability × exposure × criticality
onset      = first frame at which calibrated P crosses the operating point
```

> **🎤 The honest line:** *"The flood probability is **learned**. The asset
> overlay is **exact geometry** — nobody wants a neural net guessing where
> hospitals are."*

> ⚠️ **A wording correction that was made and matters:** `onset` is the first
> frame at which probability **crossed** the operating point, which is
> **retrospective**. Say *"flagged since 05:30 IST"* — **never** *"water expected
> from 05:30"*, because we do not produce a time-to-arrival forecast.

---

## 6.7 Calibration — what isotonic regression does and why

### The problem it solves

A raw LightGBM output is a **score**. It is monotonically related to probability
but it is **not** a probability. The model might output 0.8 for events that
actually happen 45% of the time. That number is unusable for a warning system,
because a duty officer cannot act on a scale whose meaning is unknown.

### What isotonic regression does

It fits a **monotonic (non-decreasing) step function** that maps *raw score →
observed frequency*, learned from held-out data.

```
raw score:      0.1   0.3   0.5   0.7   0.9
observed rate:  0.02  0.09  0.21  0.44  0.78
                 └──── the isotonic map bends the scores onto this ────┘
```

"Isotonic" just means "order-preserving": if score A > score B, then calibrated
A ≥ calibrated B. It can never re-rank predictions — **it only changes what the
numbers mean, never who is ranked highest.**

### Fitted on VAL 2024 ONLY

- **Not on train** — the model already fits training data, so the map would learn
  nothing.
- **Not on test** — that is cheating.
- **On the validation year, and only there.** That is why the split exists.

### Why isotonic and not Platt scaling?

**Platt scaling** fits a sigmoid — it *assumes* the miscalibration has a
particular S-shaped form, and needs little data. **Isotonic** is
**non-parametric** — it assumes only monotonicity, and can correct arbitrary
distortions. It needs more data to avoid overfitting the steps.

**We have 492,000 validation rows. Isotonic is comfortably the better choice.**

### One implementation detail worth knowing

The saved booster files are **raw LightGBM** — the calibration was never
persisted alongside them. So `precompute.py` **refits isotonic at precompute
time, on the VAL split, never on test.** Same map, same data, recomputed. Worth
knowing so you are not surprised if asked "where is the calibrator stored?"

### Reliability diagrams — Proof P-2

Bin the predictions, plot **predicted probability (x)** against **observed
frequency (y)**. A perfectly calibrated model lies on the **diagonal**.

These are saved to `reports/` and rendered inside the product's `/verify` view.
**Trust is a feature, not an appendix.**

### The operating point

The probability threshold used to turn a probability into a yes/no alert is
**not** a magic 0.5. It is **the threshold that maximises CSI at a
forecaster-acceptable FAR, chosen on validation.** The trade-off curve is
displayed — never a single number presented as if it fell from the sky. That is
charter rule **R7**: fitted, not hardcoded.

---

## 6.8 Every metric, explained

### Why "accuracy" is a forbidden word here

Heavy rain at a specific point in a specific hour happens roughly **1%** of the
time. A model that says *"no heavy rain"* forever is **99% accurate** and
completely worthless.

**That is why we refuse to give a single accuracy number, and why the question
is a trap.** All the metrics below exist specifically because accuracy is
meaningless for rare events.

### The contingency table — where three of them come from

```
                          IT ACTUALLY HAPPENED
                            YES         NO
                        ┌──────────┬──────────┐
   WE          YES      │   HIT    │  FALSE   │
   PREDICTED            │   (a)    │  ALARM   │
                        │          │   (b)    │
                        ├──────────┼──────────┤
               NO       │  MISS    │ CORRECT  │
                        │   (c)    │   NO     │
                        │          │   (d)    │
                        └──────────┴──────────┘
```

**All three metrics below deliberately IGNORE box (d)** — because (d) is the 99%
of "nothing happened, we said nothing" that would drown everything.

| Metric | Formula | Plain English | Range | Direction |
|---|---|---|---|---|
| **POD** *Probability of Detection* | `a / (a+c)` | *"Of everything that actually happened, what fraction did we catch?"* | 0–1 | **HIGHER better** |
| **FAR** *False Alarm Ratio* | `b / (a+b)` | *"Of everything we warned about, what fraction was wrong?"* | 0–1 | ⚠️ **LOWER better** |
| **CSI** *Critical Success Index* | `a / (a+b+c)` | *"Of everything that mattered — things that happened plus things we claimed — how much did we get right?"* | 0–1 | **HIGHER better** |

**Why you need all three:** you can trivially get **POD = 1.0** by warning
constantly. You can trivially get **FAR = 0** by never warning. **CSI is the
balanced one** — it punishes both over-warning and under-warning — which is why
it is the standard operational metric for rare events, and why it is our main
score.

**Rough feel for CSI:**
| CSI | Interpretation |
|---|---|
| ~0.05 | barely better than noise |
| **0.10–0.15** | **real but weak skill — where we are** |
| 0.3+ | good |
| 0.5+ | excellent, essentially unheard of for point-scale hourly heavy rain without radar |

### Brier score

```
Brier = mean of (predicted_probability − actual_outcome)²
```
**"When you said 70%, how wrong were you?"** Range 0–1. **LOWER better.**

Say 0.8 and it happens (=1) → error `(0.8−1)² = 0.04`. Say 0.8 and it does not
(=0) → error `0.64`.

**CSI asks *did you point at the right places*. Brier asks *did your confidence
number mean anything*.** These are genuinely different skills — RainFuse is
mediocre on the first and excellent on the second, and that is the honest story.

Brier decomposes into **reliability + resolution − uncertainty**, which is why it
pairs naturally with a reliability diagram.

### ROC-AUC and AUC-PR (InundaNet)

| Metric | Plain English | Reference point |
|---|---|---|
| **ROC-AUC** | *"Pick one flooded cell and one dry cell at random. What is the probability the model scores the flooded one higher?"* | **0.5 = coin flip**, 1.0 = perfect |
| **AUC-PR** | Same idea, but weighted for rare events so it is not flattered by the mass of easy negatives | **Compare against the base rate.** Ours is 7.1%, so random = **0.071** |

**Our AUC-PR of 0.611 against a base rate of 0.071 is 8.6× random**, and **9.8×
the HAND-only baseline of 0.062.** Always quote AUC-PR *with* its base rate — a
number alone is meaningless.

### Why we report per-lead and per-threshold, never one number

> **🎤 The answer to "what is your accuracy?":** *"We refuse a single number on
> rare events, because it misleads. We report CSI, POD and FAR **per lead and per
> threshold**, Brier **with** the reliability curve, and the operational
> headline. All of it is inside the product on the Verification screen, so you can
> check it yourself rather than take our word."*

---

## 6.9 SHAP — how "78%" becomes "because it is next to an underpass"

**SHAP** = *SHapley Additive exPlanations*. The idea comes from cooperative game
theory: if a team achieves a result, how much did each player contribute?

Here the "players" are features and the "result" is the prediction. SHAP answers:
**for THIS specific ward, how much did each feature push the probability up or
down from the average?**

```
base rate (average prediction over all cells)         0.07
  + near an underpass (0 m)                          +0.31
  + impervious (0.83)                                +0.18
  + antecedent rain (3-day, high)                    +0.12
  − slope (slightly steep)                           −0.05
  ────────────────────────────────────────────────────────
  = 0.63  for THIS ward
```

**Why it matters here — three reasons:**

1. **It is exact for trees.** **TreeSHAP** computes exact Shapley values for tree
   ensembles in polynomial time. This is not an approximation or a heuristic —
   unlike saliency maps on a neural network, which judges rightly distrust.
2. **The contributions sum exactly to the prediction.** So the explanation is
   *complete*, not a suggestive selection.
3. **It is per-prediction, not global.** Feature importance tells you what
   matters on average. SHAP tells you what mattered **for Minto Bridge, right
   now** — which is what a ward officer needs.

**In the product:** the top-3 SHAP drivers per ward are rendered **as plain-word
bars** — `"low HAND"`, `"impervious"`, `"antecedent rain"`, `"near an underpass"`
— in the ward detail panel, and they are what the AI advisory narrates.

---

## 6.10 🎤 JUDGE QUESTIONS — modelling

**"Why LightGBM and not deep learning?"**
> Model ladder by evidence: persistence, then pySTEPS, then gradient boosting,
> then deep nets — and you only climb a rung when you have measured and beaten the
> one below. On this data volume and this timeline, boosted trees beat a
> half-trained U-Net, train in seconds on CPU, and explain themselves through
> exact TreeSHAP. More fundamentally: deep nowcasting networks like SmaAt-UNet and
> ConvLSTM consume **sequences of radar images**. We do not have decoded radar, so
> there is literally nothing for a convolution to operate on. They are scheduled
> for the radar era, where they actually pay off.

**"Your CSI is low."** *(you will get this — here are the exact words)*
> Yes — 0.13 on point-scale hourly heavy rain, and I am not going to dress that
> up. Nobody achieves high CSI on this task without radar. What matters is the
> comparison **on identical rows**: persistence scores 0.049 and raw GFS scores
> 0.015. We are **2.7× persistence and 8 to 14× the global physics model**, and
> the honest skill-decay curve is on the Verification screen. If we were quoting
> a high absolute number on this problem, you should be suspicious of us.

**"Why should I trust an 80% probability?"**
> Because it is **isotonic-calibrated on a held-out year**, and the reliability
> diagram is **one click away inside the product**. When PRAVAAH says 80%,
> historically it happened about 80% of the time. And the threshold we use to turn
> that probability into an alert is not a magic 0.5 — it is the CSI-maximising
> point at an acceptable false-alarm ratio, chosen on validation, with the whole
> trade-off curve displayed.

**"Which parts are ML and which are rules?"**
> **Learned:** rain probabilities, the NWP correction, flood probability, and the
> SHAP drivers. **Deterministic and proudly so:** the exposure overlay — nobody
> wants a model guessing where hospitals are — plus CAP formatting and routing.
> **Fitted, not hardcoded:** thresholds, the stream network threshold, the risk
> weights. Every constant traces to a script in the repo that fitted it. The
> stream threshold, for instance, was grid-searched over five values against OSM
> waterways and chosen by F1 score.

**"Is the AI doing the forecasting?"**
> No. Three LightGBM models do the forecasting from the fused cube. The narration
> layer is a **template that can only interpolate fields present in the model's
> own JSON** — it is **structurally incapable** of inventing a figure. When an LLM
> is used, there is a post-check that every number it wrote appears in the input,
> and the output is rejected if it invents one. The models forecast; the AI
> explains.

**"What if a source fails during operation?"**
> The models are trained with **random source dropout**, so "radar out" and
> "satellite lagging" are **real, valid model outputs rather than crashes**. The
> UI badges the degradation and the uncertainty intervals widen accordingly. We
> can toggle it live. And architecturally, LightGBM handles missing values
> natively — we keep absent columns as NaN rather than imputing, and carry an
> `nwp_n_models` column so the model knows how many sources actually spoke.

**"You have three models. Is that not over-engineering?"**
> They answer three genuinely different questions on three different timescales
> with three different truth sources, and our own ablation proves they are not
> interchangeable. At 0–6 hours, removing NWP **improves** the model and raw GFS
> scores 0.015 — observations own that window. At 24 hours, NWP **is** the signal
> and our job is to correct it. And neither of them says anything about where water
> collects on the ground, which is what the problem statement actually asks for.
> One model spanning all three would be worse at all three.

---
---

# PART 7 — INFERENCE: how a prediction reaches the screen

---

## 7.1 Training vs inference — two different things people confuse

| | **TRAINING** | **INFERENCE** |
|---|---|---|
| What it does | Learns the relationship between features and the answer | **Applies** the learned relationship to new inputs |
| When | Once, offline, days ago | Every time you want a prediction |
| Needs | Millions of historical rows **with the answers** | One row of features, **no answer** |
| Output | A `.txt` booster file (the trained trees) | A number |
| Cost | Seconds to minutes on CPU | **Milliseconds** |
| In this repo | `models/raincast_v0.py` etc. | `scripts/precompute.py` and `scripts/live_update.py` |

**The models are already trained. They are files on disk:**
```
models/raincast_v0_p5_w1.txt  … 12 files   (RainCast heads)
models/rainfuse_v0_heavy.txt  … 2 files    (RainFuse categories)
models/inundanet_v0.txt       … 1 file     (InundaNet)
```

> **A judge may ask "do you retrain during the demo?" — Answer: no, never. The
> models are frozen artefacts. Inference is a lookup through a set of trees and
> takes milliseconds.**

---

## 7.2 The REPLAY path — precomputed historical events

**This is the 28 June 2024 demo.**

### What happens, step by step

```
scripts/precompute.py                                    [ONE TIME, OFFLINE]
  │
  ├─ loads InundaNet booster              (inundanet_v0.txt)
  ├─ loads 12 RainCast boosters           (raincast_v0_*.txt)   ← NEW
  ├─ loads 2  RainFuse boosters           (rainfuse_v0_*.txt)   ← NEW
  │    …both refit isotonic on the VAL split at load time
  │
  └─ for each of 15 timestamps  (00:00Z → 07:00Z, 30-min steps):
        │
        ├─ cube.at(t)          ← ONLY data issued ≤ t. The honesty law.
        ├─ run InundaNet over the 100 m grid  → p_flood per cell
        ├─ aggregate cells → 289 wards        → onset, peak, ci90, drivers
        ├─ spatial-join exposure              → people, hospitals, schools, roads
        ├─ run RainCast p5_w3 / p10_w3        → the nowcast rain grid
        ├─ run RainFuse on 64.5/115.6/204.5   → the forecast block
        │
        └─ write 4 files:
             wards_{HHMM}.geojson      289 polygons + all properties
             rain_grid_{HHMM}.json     56 lattice cells + probabilities
             kpi_{HHMM}.json           5 top-bar numbers + source badges
             advisory_{ward}_{HHMM}.json   cached bilingual text
```

**Result:** 60+ files plus **180 cached advisories**, all committed to git.

### Why 28 June 2024 — and why it is not cherry-picked

**228 mm at Safdarjung, highest June daily total since 1936, IGI terminal canopy
collapsed.** The most recognisable Delhi rain disaster in living memory.

**And the choice was validated independently.** We pulled IMD's own gridded
extreme-day catalogue and it ranked **2024-06-28 as the #1 wettest day of 2024**
(150.7 mm). The same check **disqualified** one of the charter's original events
— 2020-07-19 did not make the top 12 — so it was dropped. **The event list was
audited, not chosen by feel.**

### What Replay actually does

It steps through the 15 precomputed frames as a clock, at 10× speed:

| | 00:00Z | 03:00Z | 05:00Z |
|---|---:|---:|---:|
| wards at HIGH risk | 27 | 45 | **50** |
| people exposed | 7.3 M | 7.9 M | **8.0 M** |
| max `p_flood` | 0.784 | — | **0.841** |

**It is a recording, played frame by frame. It is not re-simulating anything.**

### Why Replay exists — the scientific justification

You **cannot** demo a live forecast, because nothing is flooding today. Replay
lets you say:

> *"At 01:30Z, using only data that existed at 01:30Z, PRAVAAH flagged Minto
> Bridge at 78%."*

…and then show what actually happened. **That is a hindcast** — a standard,
respected way to validate any new forecasting system in operational meteorology.
It is how IMD would evaluate a new model themselves.

**And the honesty law is baked into the artefact:** because `wards_0130.geojson`
was generated *through* `cube.at(01:30Z)`, it is physically incapable of
containing information from 02:00Z. Replay is **just the clock** — the filtering
already happened at generation time.

> ⚠️ **A trap that was caught:** the demo window was originally 0400–0930Z, which
> is **09:30–15:00 IST — after the storm.** The actual box-max hourly rain was
> 0.6 mm at 00:00Z, peaking at **32.9 mm at 01:00Z (06:30 IST)**, decaying to 3.2
> by 06:00Z. Window moved to **0000–0700Z, 15 frames.** Classic UTC/IST trap.

---

## 7.3 The LIVE path — what happens when you press refresh

**This landed in commit `8aeed38` and it changes the pitch materially.** Before
it, every screen showed one historical day and the Live/Replay toggle was
decorative.

### The problem it solves

The models need **recent observed rain at all 56 lattice points** to build lags,
accumulations and advection features. But **the archive API (A1) lags about five
days** — it cannot serve "now."

**The solution:** the live forecast endpoint `api.open-meteo.com/v1/forecast`
with **`past_days=2`** returns the model's recent past hours *alongside* the
forward forecast, **at every point, in one single call.** 56 points cost one
request rather than 56.

### The flow

```
scripts/live_update.py                      [runs on demand, or --loop every 15 min]
  │
  ├─ 1. FETCH   one call to api.open-meteo.com/v1/forecast
  │             past_days=2, forecast_days=2, timezone=UTC, 56 points
  │
  ├─ 2. FEATURES  rebuild the EXACT RainCast feature set:
  │               lags, accumulations, antecedent indices,
  │               the 18 advection/neighbour columns,
  │               + static terrain per lattice point (cached across updates)
  │
  ├─ 3. PREDICT   RainCast heads  → nowcast probabilities
  │               InundaNet       → ward flood probabilities
  │
  ├─ 4. PUBLISH   12 trailing hourly frames as event id 'live'
  │               → data/outputs/live/
  │
  └─ 5. ATOMIC SWAP
         writes to a TEMP directory, validates, then swaps in.
         A failed pull leaves the previous good snapshot untouched.
```

### The failure policy — this is good engineering, mention it

> *"This runs unattended every 15 minutes on a laptop that may lose wifi
> mid-demo. Therefore: **never destroy a good published state.** Everything is
> written to a temp directory and swapped in atomically only after it validates."*

**And it was verified the hard way:** the first run *failed* on missing `static_*`
features and **correctly retained the prior state.** The failure path is tested,
not assumed.

### The backend support

| Endpoint | What it does |
|---|---|
| `GET /api/live/status` | Returns **age**, a **stale flag**, and `last_error` |
| `POST /api/live/refresh` | **Async.** The UI polls status rather than waiting — *a 30-second synchronous request looks broken to a presenter* |

Also: `_index()` is now keyed on `index.json`'s **mtime**, so a live update is
visible **without bouncing the server.**

### The honesty label — say this before a judge asks

> **The live observation source is Open-Meteo's forecast API with
> `past_days=2` — that is an ANALYSIS, not a gauge reading.** It is written on
> screen. It is the best freely available "what is happening right now" at 56
> points with no credentials.
>
> **The genuine observation is the decoded SRI radar product** our logger captures
> every 10 minutes, and the file is deliberately structured so that **swapping the
> observation source is a one-function change.**

---

## 7.4 The backend — FastAPI as a file reader

### The philosophy

> **The models never run during the demo.** FastAPI is a **thin file reader**.
> Replay is just the clock. **If every API on Earth is down on demo day, the demo
> does not notice.**

**Hard rule:** if you find yourself importing `lightgbm` in `serve/`, stop —
something has gone wrong.

### The endpoints

| Endpoint | Returns | Reads |
|---|---|---|
| `GET /api/events` | Curated event list + available timestamps | `outputs/index.json` |
| `GET /api/state` | City KPIs at clock `t` | `kpi_{t}.json` |
| `GET /api/wards` | Ward GeoJSON with `p_flood`, `onset`, drivers, exposure | `wards_{event}_{t}.geojson` |
| `GET /api/rain` | Rain probability grid (`nowcast` \| `forecast`) | `rain_grid_{event}_{t}.json` |
| `GET /api/ward/{id}` | Single-ward detail: timeline, SHAP drivers, assets | slice + `timeline_{ward}.json` |
| `GET /api/frames` | pySTEPS / radar animation frame URLs | `outputs/{event}/frames/` |
| `POST /api/advisory/{id}` | Bilingual advisory. **Cache-first** | `advisory_{event}_{ward}_{t}.json` |
| `GET /api/cap/{id}` | **Mock CAP-format XML alert** | generated from ward properties |
| `GET /api/cap/{id}/preview` | Human-readable CAP preview | |
| `GET /api/live/status` | Live snapshot age + stale flag + last error | |
| `POST /api/live/refresh` | Triggers an async live update | |
| `GET /api/verify/metrics` | Reliability, skill-vs-lead, ablation, lead-time | `reports/metrics.json` |
| `GET /api/health` | Logger freshness + which sources feed the view | health check |
| `StaticFiles /` | The built React app | **One origin, zero CORS, offline** |

### Replay mechanics

The frontend clock picks `t`; **every endpoint filters to artefacts stamped ≤ t.**
Because the outputs were generated through the cube's latest-at-`t0` accessor,
replay **automatically** shows only what was knowable at that moment. *The same
honesty law, enforced end to end.*

### The advisory layer — three tiers, and it ships without an API key

```
1. DISK CACHE            ← what the demo actually serves. 180 pre-generated.
2. DETERMINISTIC RENDERER ← the FLOOR, not a stopgap
3. LLM (Claude / Gemini)  ← only if online AND cache miss
```

**Why the deterministic tier is the strongest answer to "is the AI forecasting?":**
> It **can only interpolate keys that exist in the input contract**, so it is
> **structurally incapable of inventing a figure.** That is a stronger guarantee
> than any prompt instruction.

**And when the LLM path is used**, there is a **post-check that every number it
wrote appears in the input JSON**, and the output is **rejected** otherwise.

**The iron rule:** *"The LLM never predicts. It narrates numbers the models
already computed. The models forecast; the AI explains."*

---

## 7.5 The frontend — six views and what each proves

**React 18 + Vite + MapLibre GL + Recharts + Tailwind + zustand.**
**Not Next.js** — no SSR needed, and a plain Vite build produces a static bundle
FastAPI serves from one origin, fully offline.

| Route | View | What it proves | Cuttable? |
|---|---|---|---|
| `#/command` | **Command Center** | It is an operational product, not a notebook | ❌ **NEVER CUT** |
| `#/inundation` | **Inundation + Impact** | **The USP** — rain → water → people | ❌ **NEVER CUT** |
| `#/replay` | **Replay** | The honesty law, on a real disaster | ❌ **NEVER CUT** |
| `#/verify` | **Verification** | The four proofs, checkable | high value, low risk |
| `#/nowcast` | Nowcast | 0–6 h skill and its honest decay | bonus |
| `#/forecast` | Forecast | 6–72 h correction vs raw physics | bonus |

### What `/verify` is — since this confused you

**It is a page, not a command and not a file.** Open:
```
http://localhost:8000/#/verify
```
It renders `reports/metrics.json` via `GET /api/verify/metrics`: reliability
diagrams per model head, skill-vs-lead curves, **the ablation table**, the
lead-time verdict, and the stated-limits list. **A static render of `reports/` —
zero runtime risk.**

**It is aimed squarely at IMD judges.** It is where you prove you are honest.

### The offline gate — a hard requirement, not an optimisation

- **No external basemap tiles.** Every layer is our own GeoJSON on a dark canvas:
  ward polygons, drains, roads, water bodies, asset markers, **1,305 underpasses**.
  Built from OSM data already on disk → **6.3 MB served from localhost**.
  *(roads_minor — 239,283 features, 43 MB — was deliberately excluded.)*
- **Fonts bundled locally.** Inter, no Google Fonts CDN.
- **The only network calls the app ever makes are to `localhost`.**
- **Acceptance test: wifi OFF, cold start, full 3-minute demo, zero console
  errors.**

**On your question about live satellite imagery:** the charter explicitly allows
*"an online basemap toggle (CARTO dark) that defaults OFF."* It is sanctioned but
not built. **My honest read:** the dark control-room aesthetic reads as
*operational* to disaster-management judges, which is a stronger signal than a
consumer satellite map. If you add a satellite toggle, make it default-off and
scope the preflight external-host check so it does not fail the offline gate.

### `make` and `make preflight` — since you asked

**`make` is GNU Make**, a build tool from 1976 that ships with macOS. It has
**nothing to do with FastAPI.** A `Makefile` is just a list of named shortcuts:

```makefile
CONDA_RUN = $(HOME)/miniforge3/bin/conda run -n pravaah --no-capture-output

serve:
	$(CONDA_RUN) uvicorn serve.main:app --reload --port 8000
```

So `make serve` runs that full command. **Why bother?** Because without it you
must remember to activate the right conda environment first — and running
`uvicorn` in the wrong environment gives an import error and wastes ten minutes.
**`make serve` guarantees the right Python every time.**

**`make preflight`** runs `scripts/preflight.py` — **13 automated gates** that
answer "is this demo safe to run":

| Gate | Protects against |
|---|---|
| No-look-ahead suite, 6/6 | Leakage — the credibility killer |
| Artefacts complete per event | A missing file → blank map mid-demo |
| No stale artefacts | Files from a superseded run |
| Advisories match the map | Text says 78% while the map says 61% |
| **No external hosts in served files** | **The offline gate** |
| Each logger capturing recently | A dead logger you did not notice |
| metrics.json present + ablation + reliability + limits | An empty `/verify` screen |
| No placeholder values left | A `[FAKE]` string reaching a judge's screen |

**Run it right before you present.** `13/13 PASS` = clear.

### `caffeinate` — the honest answer

`caffeinate -is` prevents macOS sleep: `-i` blocks idle sleep, `-s` blocks system
sleep **on AC power**.

| Scenario | Do the loggers survive? |
|---|---|
| Idle on a desk, plugged in, terminal open | ✅ **Yes** — exactly what it is for |
| You close the terminal window | ❌ **No.** caffeinate dies, loggers die with it |
| You **close the lid** | ⚠️ **Usually no.** `-i` does not prevent lid-close sleep |
| You **shut down** | ❌ **No** |
| On battery, lid open, idle | ⚠️ Unreliable — `-s` only applies on AC |

**So: loggers run only while the Mac is awake, plugged in, lid open, and that
terminal is alive.** The charter specified a GitHub Actions cron mirror as a
backup; **it was never built.** Keep the lid open and plugged in through the
demo.

---

## 7.6 🎤 JUDGE QUESTIONS — the product

**"Is this live, or is it a recording?"** *(the most likely product question)*
> **Both, and the distinction is on screen.** The **Replay** tab is a hindcast of
> 28 June 2024 — precomputed, frame by frame, where every frame used only data
> issued before that frame's clock. The **Live** tab pulls current conditions for
> all 56 lattice points, rebuilds the feature set, runs RainCast and InundaNet,
> and republishes — with an age badge and an honest label saying the observation
> source is an analysis, not a gauge. We precompute rather than infer on request
> because venue wifi is not a dependency we are willing to have.

**"Why is there no Predict button?"**
> Because there is nothing to press — by design. Every answer for every frame is
> already computed and sitting in a file, and FastAPI is a thin file reader that
> never loads a model. That is what makes the demo airplane-mode safe. The **live
> refresh** button is the closest thing: it triggers an asynchronous pull-predict-
> publish cycle, and the UI polls status rather than blocking, because a
> thirty-second synchronous request looks broken to a presenter.

**"If the models are precomputed, how do I know they are not just hardcoded
numbers?"**
> Three ways you can check right now. **One:** `scripts/precompute.py` loads the
> booster files and calls them — you can read it. **Two:** press live refresh and
> the numbers change, because it re-runs the models against a fresh pull. **Three:**
> retrain a model and the files change, but nothing in `serve/` or `ui/` changes,
> because the frozen contracts sit between them — we proved that when the fake
> files were swapped for real model output and **zero code changed** on either
> side.

**"What if the internet is down at the venue?"**
> The entire demo runs offline and that is a hard gate we test, not an
> aspiration. No external basemap tiles — the map is 6.3 MB of our own GeoJSON on
> a dark canvas. Fonts are bundled locally. The only network calls the app makes
> are to localhost. The preflight gate greps every served file for external hosts
> and fails if it finds one. The only thing that stops working offline is the live
> refresh, which degrades gracefully to the last good snapshot with an honest age
> badge.

**"A judge asks for a prediction for today."**
> Press live refresh. It pulls current conditions for the 56 lattice points, runs
> RainCast and InundaNet, and publishes twelve trailing hourly frames. Framed
> honestly: this is a live view on an analysis-grade observation, refreshed just
> now.

---
---

# PART 8 — SCALE, PORTABILITY AND ECONOMICS

---

## 8.1 The honest answer: which model is the bottleneck

**Your instinct is correct, and here it is precisely.**

| Model | Can it go national? | The real constraint |
|---|---|---|
| **RainFuse** | ✅ **It already is multi-state today** | None. Pull time only |
| **RainCast** | ✅ Technically yes | **Pull volume + regional weather regimes** |
| **InundaNet** | ⚠️ **This is the blocker** | **LABELS.** Not compute, not terrain, not money |

> **🎤 The line to say:** *"The rainfall layer runs nationwide today — it is
> grid-based and region-agnostic. Only the inundation layer is Delhi-specific,
> because inundation needs per-city terrain and per-city labels. Terrain is
> automatable. Labels are not — and that is the honest constraint."*

---

## 8.2 RainFuse — already multi-state today

**It was never a Delhi model.** It was trained on the **wide NW-India domain:**

```
70–84 °E, 21–33 °N      ≈ Rajasthan, Punjab, Haryana, Delhi, UP, MP
195 NWP points × 2,793 IMD gridded cells
1.36 MILLION rows
```

**The data behind it covers all of India, free, with no account:**
- Open-Meteo Historical Forecast API — global
- IMD gridded via `imdlib` — all-India, 1901–2024

**So RainFuse could go national essentially tomorrow.** The only cost is pull
time and training time, both measured in hours.

> **💡 A nearly-free pitch win:** RainFuse is *already trained* on six states.
> Rendering one map of its predictions across that domain costs almost nothing and
> **visually destroys the "only one city?" question before it is asked.**

---

## 8.3 RainCast — national is possible, with one real caveat

**Data availability is not the problem.** Open-Meteo's archive covers all of
India, free, no key.

**The cost is pull volume:**

| Scope | Lattice points | Rough pull time |
|---|---:|---|
| Delhi NCR at 0.1° | **56** | **11 minutes** ✅ done |
| All-India at 0.25° | ~6,000 | ~20 hours |
| All-India at 0.1° | ~40,000 | days, plus rate limits |

**The modelling caveat — and you spotted this yourself:**

> **Rainfall behaves differently across India.** Kerala's coastal monsoon,
> Delhi's convective cloudbursts, and Himalayan orographic rain are **three
> different physical regimes.** A single model trained on all of them would need
> regional features, or you would train per-region models.

**You are right that this is a real constraint on RainCast — but note it is a
softer one than InundaNet's.** It is solvable with more data and regional
features. It does not require a dataset that does not exist.

---

## 8.4 InundaNet — labels are the blocker, not compute

Two dependencies per city. Only one of them is hard.

### Dependency 1 — terrain processing. **NOT the blocker.**

DEM → HAND, TWI, slope, flow accumulation at 100 m. **Copernicus GLO-30 covers
the entire planet**, free, unsigned S3. The pipeline is fully scripted. For any
Indian city this is a **mechanical geoprocessing job** — hours of compute, zero
human decisions.

**This genuinely IS config-file portable**, and that is what `aoi_chennai.yaml`
proves: it was derived mechanically and **loads through `grid.py` with zero code
changes.**

### Dependency 2 — LABELS. **This is the blocker.**

To train a supervised model you must show it examples: *"here is a place that
flooded, here is a place that did not."*

For Delhi we hand-built **84 points** from Delhi PWD lists, Delhi Traffic Police
waterlogging lists and news reports — with per-point confidence grades, an OSM
cross-check, a separation distance and a holdout flag.

> **There is no machine-readable urban waterlogging dataset for ANY Indian city.**
> Not Delhi, not Mumbai, not Chennai. To do Mumbai you would hand-build Mumbai's.
> To do 4,000 cities you would hand-build 4,000 label sets.

**That does not scale by config file. That is the honest constraint.**

> **🎤 Say it plainly — this is a strength, not an excuse:** *"There was no
> machine-readable Delhi waterlogging dataset, so we built one by hand, graded
> each point's confidence, and treated it as a deliverable in its own right.
> Being able to say we built the label set because none exists is a strength.
> But it is also why we are honest that a second city is not a config file — the
> terrain is, the labels are not."*

---

## 8.5 How we break the label constraint

**This is the roadmap answer when a judge pushes on scaling.**

### 1 · Sentinel-1 SAR — the actual unlock

**What it is:** Synthetic Aperture Radar in orbit (ESA). Radar **sees through
cloud** — which is the whole point, because a flood happens *under* the storm and
optical satellites are blind exactly then. And **water is smooth**, so it
reflects radar away from the sensor and appears **dark**.

**Compare a before-image and an after-image and flood extent falls out almost
automatically.**

**Free on AWS via Earth Search** (`earth-search.aws.element84.com/v1`) — **no
account gate**, unlike Copernicus GFM which sits in an approval queue.

> **This turns "84 hand-built points in one city" into "thousands of
> automatically-derived flood polygons anywhere in India."**

**⚠️ The honest caveat, and say it:** SAR struggles in **dense urban cores** —
buildings scatter the signal in ways that confuse water detection. Which is
exactly where Delhi's blackspots are. So it is a **partial** unlock: excellent
for riverine and peri-urban flooding, weaker for underpasses.

### 2 · Global Flood Database (A6) — free, and we never pulled it

MODIS-derived flood extents, 2000–2018, at 250 m, on GEE — **and our GEE project
is already authenticated.** 250 m will not resolve an underpass, but it is
national and free. **It is the cheapest label expansion available and it is a
genuine miss in v0.**

### 3 · Ship susceptibility where you have no labels

For a city with zero labels you can **still** produce the **static susceptibility
map** — terrain + impervious + underpass distance. **That needs no training data
at all.**

So the honest scaling claim becomes:

> *"Any Indian district gets a **susceptibility map** in hours from a config
> file. Turning that into a **calibrated probability** needs labels — and SAR is
> how we get those without a field campaign."*

### 4 · The dataset that would help most, and where it lives

> **Municipal drainage capacity.** We proxied it with OSM underpasses and it
> became our #2 feature. **The real thing lives with the MCD and the Delhi Jal
> Board.** That is a concrete, specific ask — far better than "we would like more
> data."

---

## 8.6 What it would actually cost to run nationally

**The honest economics, which almost no hackathon team can answer.**

### Data cost: ₹0

Every source is free and public. Open-Meteo, the AWS open-data buckets
(Copernicus DEM, WorldCover), OSM, JRC GHSL/GHS-POP, `imdlib`. **There is no free
tier to run out of** — this is public infrastructure. GEE is free for
non-commercial use and we used it for exports only, never compute.

### Compute cost: negligible, and that is a deliberate design choice

| Job | Frequency | Cost |
|---|---|---|
| **Heavy geoprocessing** (DEM → HAND/TWI/slope) | **Once per district, ever** | Hours of CPU |
| **Model training** | Once, or on retrain | **Seconds to minutes on CPU** |
| **Inference** | Per district, per cycle | **Seconds on CPU** |
| **GPU** | — | **None. Nothing in v0 needs one** |

> *"Nothing in this system needs a GPU. LightGBM on the NCR lattice trains in
> under a minute on a laptop CPU. The bottleneck in this project was never
> compute — it was data wrangling."*

### The scaling shape

| Component | How it scales |
|---|---|
| **Rainfall layer** | **Horizontally and cheaply.** Grid-based inference is seconds per district |
| **Terrain layer** | **Once per district**, then free forever |
| **Loggers** | Horizontal — one process per feed |
| **Labels** | ⚠️ **The only human-cost item.** SAR is how you remove it |

### The pilot ask — the slide-8 answer

> **A pilot with one Flood Met Office and raw radar access for Delhi.**
>
> Three things we would do with agency access, in order:
> 1. **Raw DWR volumes** to replace GIF display — better 0–2 h skill
> 2. **The AWS gauge archive** to recalibrate every truth layer
> 3. **NCUM / BharatFS** as a fourth NWP column
>
> **Each lands as one adapter and one new ablation row — measurable, not
> rhetorical.**

---

## 8.7 🎤 JUDGE QUESTIONS — scaling and money

**"Only one city? That is not a national solution."**
> The rainfall layer is **not** one city. RainFuse is trained on 195 NWP points
> and 2,793 IMD cells across six states of northwest India — it was never a Delhi
> model. RainCast's data covers all of India for free; extending it is pull time,
> not a research problem. **Inundation is the part that is Delhi-specific, and it
> is specific for one reason: labels.** Terrain is automatable and we prove it —
> our Chennai config loads through the pipeline with zero Python changed. But there
> is no machine-readable waterlogging dataset for any Indian city, so we hand-built
> Delhi's 84 points. Scaling that is exactly what Sentinel-1 SAR solves, and it is
> first on our roadmap.

**"So what is your actual bottleneck?"**
> Supervised learning needs labels, and open flood labels do not exist in India.
> Not compute — nothing here needs a GPU. Not money — every source is free. Not
> terrain — Copernicus DEM covers the planet and our pipeline is scripted. **It is
> ground truth about where water actually stood.** And we have a concrete plan to
> break it: SAR sees through cloud and water appears dark, so a before-and-after
> image pair gives flood extent automatically, free on AWS with no account gate.

**"What would this cost to run for all of India?"**
> Data cost is zero — every source is public infrastructure, not a metered API.
> Compute is negligible and deliberately so: heavy geoprocessing runs **once per
> district**, training takes seconds to minutes on CPU, and inference is seconds
> per district. **No GPUs anywhere.** The only human-cost item is labelling, which
> is precisely what we would replace with SAR. The realistic marginal cost of a new
> district today is a few hours of CPU plus one config file — and a label campaign
> if you want calibrated probabilities rather than a susceptibility map.

**"Would this work in a city very different from Delhi — say Chennai or Guwahati?"**
> The pipeline would run — our Chennai config already loads. The **terrain
> features** would compute correctly. What would **not** transfer is the trained
> InundaNet weights, for two reasons. First, no labels for that city. Second, the
> physics differs: Chennai floods substantially from **coastal and riverine**
> causes with a different drainage regime, whereas Delhi's blackspots are **pluvial
> underpass failures** — which is exactly why underpass distance dominates our
> feature list and might not dominate Chennai's. **We would expect to re-fit per
> region and we would say so rather than claim a universal model.**

**"Why not just use a bigger model / more data / deep learning to fix all this?"**
> Because none of those address the actual constraint. More model capacity does
> not create flood labels that do not exist. More rainfall data does not fix an
> answer key that smooths cloudbursts — our ERA5 target reads 20.9 mm where the
> gauge read 228. And deep networks for nowcasting consume radar image sequences
> that we do not have decoded. **Every one of our top three roadmap items is a data
> item, not an algorithm item.** That is what the measurements told us.

---
---

# PART 9 — HONEST LIMITS AND THE HARDEST QUESTIONS

---

## 9.1 The stated-limits list — memorise this

**These are IN the product**, on the `/verify` screen. **A limitation you state
yourself is a credential. A limitation a judge discovers is a wound.**

**1 · No ground radar.**
> IMD's raw DWR volumes are gated. We log the public imagery every 10 minutes but
> do not decode it in v0. **Radar is THE nowcasting instrument, so our 0–6 hour
> skill is bounded by its absence.**

**2 · ERA5 smooths convective extremes.**
> 20.9 mm near Safdarjung where the gauge recorded 228 mm. RainCast's thresholds
> are therefore **ERA5-scale**, and the charter's 15 mm/h head was **dropped**
> because it had only 63 test positives.

**3 · IMD gridded is only 6 cells over the NCR box.**
> A daily **areal** truth, not a ward-scale one. Gauge-based and it captures the
> extreme — but it cannot discriminate between wards, and we do not imply
> otherwise.

**4 · 84 hand-curated flood labels.**
> No machine-readable Delhi waterlogging dataset exists; we built one and graded
> each point's confidence. **Terrain alone does not explain them** — top-quintile
> enrichment 0.94. OSM underpass features are the strongest available proxy for
> the missing variable, which is **storm-sewer capacity**.

**5 · Lead-time vs CAP is not computable for this event.**
> Reported as not-computable rather than substituted quietly.

**Two more worth carrying:**

**6 · SAR is blind in dense cores.** Our own roadmap unlock has a known
weakness, and it is in the densest part of the city.

**7 · Inundation is a single pilot city.** The pipeline is portable; the trained
region is not.

---

## 9.2 The negative results we kept

**Three results went against us and all three are in the product.** This is your
strongest credibility asset — use it deliberately.

### P-1 · The ablation says fusion did NOT win

| config | CSI |
|---|---:|
| **without NWP** | **0.124** |
| fusion, consistent-coverage NWP | 0.116 |
| advection only | 0.113 |
| **ALL SOURCES** | 0.098 |
| without advection | 0.058 |
| persistence (no ML) | 0.049 |
| **raw GFS (no ML)** | **0.015** |

**Removing NWP improved the nowcast.** Diagnosed rather than patched: NWP
coverage starts at different dates (**GFS Mar 2021, ICON Nov 2022, ECMWF Feb
2024**), so a column's **missingness correlates with the year**, and the test year
is fully covered — a pattern never seen in training. Restricting to
consistent-coverage columns recovers **0.098 → 0.116**.

> **🎤 But the deeper reading is our own thesis, proven:** *"At 0–6 hours,
> observation-based advection beats global NWP — raw GFS scores 0.015. **That is
> exactly the nowcast gap we exist to fill.** And it is coherent with RainFuse,
> where NWP at 6–72 hours **is** the signal and we beat it on Brier. Present the
> negative ablation — it is a better argument than a tidy one."*

Note also: **removing advection causes the single largest drop** (−0.040). So the
ablation *does* prove a family matters — just not the family we expected.

### P-3 · Lead time is not computable

We pulled IMD's CAP archive for the 7 days around 28 June 2024: **7 alerts, all
multi-state bulletins** (Bihar, Kerala, Uttarakhand, Odisha). **None mentioning
Delhi.**

The script has an **explicit honesty gate** that refuses to compare our crossing
against Kerala's alert and writes `computable=false` with the reason.

> **⚠️ IMPORTANT FRAMING — be fair to IMD:** *"That feed is a sparse daily
> bulletin cycle, **not** IMD's city warning channel. Its silence is **not**
> evidence that IMD failed to warn Delhi, and we must not imply that it is."*

A computable substitute is reported instead: timing versus raw NWP and versus
persistence on the same event.

### IMERG · tested and not shipped

Covered in §3.3. **976 days pulled, A/B'd on identical code, made the model
slightly worse, not shipped, archive kept, and the cause diagnosed.**

> **🎤 Why you should volunteer all three:** *"Two of our four proofs came back
> negative and both are in the product. We could have quietly dropped the ablation
> and substituted a different lead-time comparison. We did not, because a judge who
> finds a soft number after you have quoted it will discount everything else you
> said."*

---

## 9.3 The full judge Q&A bank

**Quick reference. Detail lives in the section noted.**

| Question | Where the answer is |
|---|---|
| How is this different from iFLOWS / CFLOWS? | §2.6 |
| You don't have raw radar. Isn't that fatal? | §1.3, §9.1 |
| How do we know there's no data leakage? | §5.6 ← **most likely hard question** |
| What's your accuracy? | §6.8 ← **it's a trap; refuse the single number** |
| Why should we trust an 80% probability? | §6.7, §6.10 |
| Only one city? | §8.7 |
| Is the AI doing the forecasting? | §6.10, §7.4 |
| Which parts are ML and which are rules? | §6.10 |
| What if a source fails during operation? | §6.10 |
| Flood ground truth is weak. Will you admit it? | §8.4, §9.1 |
| Why LightGBM and not deep learning? | §6.3, §6.10 |
| Scale to all-India in production? | §8.6, §8.7 |
| Why did you not use MOSDAC / IMD APIs? | §3.6 |
| What would you do with agency access? | §8.6 |
| How can 56 rain points give ward output? | §4.5, §4.7 |
| Is it live or a recording? | §7.6 |
| Why is there no Predict button? | §7.6 |
| What does it cost to run? | §8.6, §8.7 |
| Explain the Doppler effect | §1.9 |
| How does a satellite measure rain? | §1.9 |

### Two more that are worth pre-drilling

**"Flood ground truth is weak. Will you admit it?"**
> Yes — **urban flood labels are the hardest problem in this field**, and I will
> not pretend otherwise. There is no machine-readable waterlogging dataset for any
> Indian city, so we hand-built 84 points from PWD and traffic-police records and
> graded each one's confidence. What keeps us honest about it is methodology, not
> claims: **5 km spatial-block cross-validation** so adjacent cells cannot leak,
> **coordinates excluded as features** so the model cannot memorise our 84
> locations, **imperviousness-matched negatives** so it cannot win by detecting
> cities, and **AUC-PR always reported beside its base rate.** Copernicus GFM and
> Sentinel-1 SAR are how that label set stops being hand-built.

**"You dropped the 15 mm head. Isn't that moving the goalposts?"**
> It is changing a threshold, and here is exactly why. The head is scored against
> ERA5, and ERA5 reads 20.9 mm on a day the gauge read 228 — it smooths convective
> extremes. At 15 mm/hr in ERA5 units there were **63 positives in the entire test
> year**, which is not enough to compute a stable score. Reporting a CSI on 63
> positives would have been the dishonest choice. So we ship 5 and 10 mm ERA5-scale
> heads, we state in the product that these correspond to substantially higher real
> rainfall, and we write the actual thresholds into the output so nothing downstream
> can misread them.

---

## 9.4 What to say when you do not know

**Three sentences that will save you, and they work because everything else in
this project has already earned them.**

**1 · When you genuinely do not know:**
> *"I don't know — that isn't something we measured. What we did measure is
> [nearest thing you did measure], and here is that number."*

**2 · When a judge finds a real weakness:**
> *"You're right, and it's on our stated-limits list on the Verification screen
> for exactly that reason. Here's what it would take to fix it."*

**3 · When you are asked to overclaim:**
> *"I could give you a single number, but it would mislead you on a rare event.
> Let me give you the three that actually mean something."*

### And the meta-rule for the whole presentation

> **Every number in this project is traceable to a file in the repo.** Nothing is
> rounded up, nothing is aspirational. Where a claim did not survive testing it is
> written as it actually came out — **because a judge who finds a soft number
> after you have quoted it will discount everything else you said.**

---

## 9.5 The 180-second click path

| time | action | say |
|---|---|---|
| **0:00–0:20** | Command Center, live radar panel | *"Running on data our loggers pulled this morning. The badges show which sources are feeding it."* |
| **0:20–1:30** | Replay 28 Jun 2024 from 00:00Z at speed | *"Watch the high-risk count go 27 → 45 → 50 as the cloudburst lands."* **Pause.** *"Everything here used only data issued before this clock."* |
| **1:30–2:10** | Click a critical ward → drivers, assets, advisory (EN + हिन्दी) | *"Top driver: near an underpass. The models forecast; the AI only narrates numbers they computed."* |
| **2:10–2:40** | Verification view | *"Our ablation says removing NWP helps at 0–6 hours. That is the gap we exist to fill — and it is why raw GFS scores 0.015 against our 0.124."* |
| **2:40–3:00** | Toggle the underpass layer, then the ask | *"Terrain could not find Delhi's blackspots. OpenStreetMap's underpass tags could. Give us raw radar and municipal drainage, and this gets substantially better."* |

---

## 9.6 The five sentences to have memorised

1. **The pitch.** *"India's best flood-warning systems exist in two cities, and
   each took years and a bespoke bathymetry survey. PRAVAAH stands up ward-level,
   probabilistic, impact-aware warning for any Indian district from free open data
   — and fills the 0–6 hour nowcast gap those systems do not cover."*

2. **The architecture.** *"Five open source families, one honesty law, three
   models, one command center."*

3. **The honesty law.** *"Every forecast row stores both when it was issued and
   what time it is about, and there is exactly one function that reads the data."*

4. **The finding.** *"Classical flood hydrology could not find Delhi's blackspots,
   because Delhi floods at underpasses from drainage-capacity failure — and
   drainage capacity is not open data anywhere in India. So we proxied it with
   OpenStreetMap's underpass tags, and that single feature took our AUC-PR from
   0.50 to 0.61."*

5. **The adapter principle.** *"Every source is an adapter emitting one shared
   record shape. The open feed in the prototype can be replaced by the IMD-native
   feed — raw DWR volumes, the AWS gauge archive, NCUM — with no change
   downstream. Approvals upgrade the system without rework, and each one lands as
   exactly one new ablation row."*

---

*End of document. Ask for any section to be expanded, or for a new topic to be
inserted — the Contents at the top is the index, and new sections slot into the
existing numbering.*
