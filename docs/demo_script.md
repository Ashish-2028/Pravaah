# PRAVAAH — deck content and the 3-minute demo

> Every number here is real and traceable to a file in this repo. Nothing is
> rounded up, nothing is aspirational. Where a claim did not survive testing it
> is written here as it actually came out, because a judge who finds a soft
> number after you have quoted it will discount everything else you said.

**Run `make preflight` before presenting.** 13 gates, all must pass.

---

## The one-line pitch

> India's best flood-warning systems exist in two cities, and each took years
> and a bespoke bathymetry survey. PRAVAAH stands up ward-level, probabilistic,
> impact-aware warning for any Indian district from free open data — and fills
> the 0–6 hour nowcast gap those systems do not cover.

---

## Slide 1 — The gap

Four facts, one map of Delhi:

- NWP models run on fixed cycles and take hours. In the 0–6 h window that
  matters for a cloudburst there is no skilful public guidance.
- Warnings are district-scale. A control room needs *"Minto Bridge, 78%, water
  by 06:30"*, not *"Delhi: heavy rain"*.
- **Rain is not flood.** 50 mm on a sealed, low-lying, badly-drained cell
  floods; the same 50 mm two streets uphill does not.
- iFLOWS-Mumbai and CFLOWS-Chennai are excellent — and cover exactly two
  cities, each after years of work and a bathymetry survey.

**Delhi — 30 million people — has neither.**

---

## Slide 2 — PRAVAAH in one picture

The architecture diagram. Say it in one breath:

> Five open source families, one honesty law, three models, one command center.

Then name the honesty law, because it is the thing that separates this from a
hackathon demo: **every forecast row stores both when it was issued and what
time it is about, and there is exactly one function that reads the data.**

---

## Slide 3 — This is running right now

Screenshot of the Command Center, plus the radar panel.

> This frame is **DWRDELHI(PALAM) Surface Rainfall Intensity, captured by our
> own logger at 22:02 IST last night.** Our loggers have been running
> continuously since 28 August — IMD's CAP alert stream every 15 minutes, radar
> imagery every 10, ECMWF runs four times a day.

**Say the limit in the same breath:** we *display* IMD's radar imagery, we do
not decode it. No model consumes those pixels. Decoding raw DWR volumes is the
roadmap ask.

---

## Slide 4 — Replay: 28 June 2024

The money slide. 228 mm at Safdarjung, highest June total since 1936, the IGI
terminal canopy collapsed.

Replay from 00:00Z. As the clock runs:

| | 00:00Z | 03:00Z | 05:00Z |
|---|---:|---:|---:|
| wards at HIGH risk | 27 | 45 | **50** |
| people exposed | 7.3 M | 7.9 M | **8.0 M** |

*(Verified against `data/outputs/2024-06-28/` on 31 Aug. If the models are
retrained, re-read these three frames before presenting — an earlier draft of
this document carried numbers from a superseded run.)*

Then pause and say the sentence that matters:

> Everything on this screen was computed only from data issued **before** this
> clock. The artefacts were generated through the same read path the leakage
> tests exercise.

---

## Slide 5 — The four proofs

**P-1 · Fusion — and this one did not go the way we expected.**

| config | CSI |
|---|---:|
| without NWP | **0.124** |
| fusion, consistent-coverage NWP | 0.116 |
| advection only | 0.113 |
| ALL SOURCES | 0.098 |
| persistence (no ML) | 0.049 |
| raw GFS (no ML) | 0.015 |

Removing NWP *improved* the nowcast. We measured why: NWP coverage starts at
different dates (GFS Mar 2021, ICON Nov 2022, ECMWF Feb 2024), so a column's
**missingness correlates with the year**, and the test year is fully covered.

**But the deeper reading is our own thesis, proven:** at 0–6 hours,
observation-based advection beats global NWP — raw GFS scores 0.015. *That is
exactly the nowcast gap we exist to fill.* And it is consistent with RainFuse,
where NWP at 6–72 h **is** the signal and we correct it.

**P-2 · Calibration.** RainFuse on IMD's official 24 h "heavy" category
(64.5 mm), tested on a held-out year: **Brier 0.0112 vs raw NWP 0.0401 — 3.6×
better calibrated.** It does not detect many more heavy-rain days than the
physics; it makes the physics' probabilities *mean* something.

**P-3 · Lead time — not computable, and we say so.** IMD's public CAP feed
carried **no Delhi-covering alert** in the 7 days around 28 Jun 2024 (7 alerts,
all multi-state). We refuse to compare our crossing against Kerala's alert. Be
careful and fair: that feed is a sparse daily bulletin cycle, **not** IMD's city
warning channel — its silence is not evidence IMD failed to warn Delhi.

**P-4 · Portability.** `configs/aoi_chennai.yaml` — a second region derived by
changing bbox, UTM zone, lattice origin, monsoon months and DEM tiles. **No
Python changed.** Honest scope: a portable *pipeline*, not a trained region.

---

## Slide 6 — Rain to people

**The finding that makes this project ours.**

Terrain alone does not find Delhi's blackspots. Two independent measurements:

- Of six known waterlogging wards, only Minto Road reached the top quintile of
  terrain susceptibility. **Jama Masjid: 3.1st percentile. Turkman Gate: 7.6th
  — while being 92% and 100% impervious.**
- Our label set shows **top-quintile enrichment 0.94** — labelled flood points
  are, if anything, slightly *less* likely to sit in high-susceptibility cells.

Why: HAND reads **14.9 m** at Jama Masjid. Three of our four checkpoint
blackspots are **underpasses** — 5–15 m engineered dips a 30 m DEM cannot see —
and they flood from *drainage capacity failure*, not topography.

**So we found the missing variable somewhere else.** Storm-sewer capacity is not
open data anywhere in India — but **OSM tags every underpass** (`tunnel=yes`,
`layer<0`). We pulled 1,305 of them.

| distance to nearest below-grade way | |
|---|---:|
| Minto Bridge | **0 m** |
| ITO | 100 m |
| Zakhira | 300 m |
| Pul Prahladpur | 1,281 m |
| **city-wide median** | **2,746 m** |

| InundaNet | before | after |
|---|---:|---:|
| AUC-PR (5 km spatial-block CV) | 0.498 | **0.611** |
| matched-negative ROC-AUC | 0.829 | **0.918** |
| lift over a HAND-only baseline | 8.0× | **9.8×** |

`underpass_dist` became the **#2 feature**. Pahar Ganj went from the 13.8th
percentile to the **87.9th**.

Then the advisory: bilingual, every figure traceable to the model JSON.

---

## Slide 7 — Honesty and roadmap

**Stated limits** (these are in the product, on the Verification screen):

1. **No ground radar.** IMD's raw DWR volumes are gated. Radar is *the*
   nowcasting instrument, so our 0–6 h skill is bounded by its absence.
2. **ERA5 smooths convective extremes** — 20.9 mm near Safdarjung where the
   gauge recorded 228 mm. So RainCast's thresholds are ERA5-scale, and the
   charter's 15 mm/h head was **dropped** because it had only 63 test positives.
3. **IMD gridded is only 6 cells** over the NCR box — a daily areal truth, not a
   ward-scale one.
4. **84 hand-curated flood labels.** No machine-readable Delhi waterlogging
   dataset exists; we built one and graded each point's confidence.
5. **Lead-time vs CAP is not computable** for this event.

**We also tested IMERG and did not ship it.** 976 days of 30-minute satellite
rain: mean CSI 0.0728 (ERA5-only) vs 0.0718 (+IMERG), 4/12 heads improved and
those four are the thinnest. Cause: our *target* is ERA5-derived, so IMERG
enters as a noisy proxy for our label rather than new information.

**Roadmap:** raw DWR decoding → Sentinel-1 SAR flood labels → agency adapters →
second region. Each lands as one adapter and one new ablation row.

---

## Slide 8 — The ask

A pilot with one Flood Met Office and **raw radar access for Delhi**.

Then the three things we would do with agency access, in order:
1. Raw DWR volumes to replace GIF display — better 0–2 h skill
2. The AWS gauge archive to recalibrate every truth layer
3. NCUM/BharatFS as a fourth NWP column

Plus the one dataset that would most improve the inundation model: **municipal
drainage capacity**. We proxied it with OSM underpasses; the real thing lives
with the MCD and Delhi Jal Board.

---

## The 180-second click path

| time | action | say |
|---|---|---|
| 0:00–0:20 | Command Center, live radar panel | "Running on data our loggers pulled this morning. Badges show which sources are feeding it." |
| 0:20–1:30 | Replay 28 Jun 2024 from 00:00Z at speed | "Watch the high-risk count go 27 → 45 → 50 as the cloudburst lands." **Pause.** "Everything here used only data issued before this clock." |
| 1:30–2:10 | Click a critical ward → drivers, assets, advisory (EN + हिन्दी) | "Top driver: near an underpass. The models forecast; the AI only narrates numbers they computed." |
| 2:10–2:40 | Verification view | "Our ablation says removing NWP *helps* at 0–6 h. That is the gap we exist to fill — and it's why raw GFS scores 0.015 against our 0.124." |
| 2:40–3:00 | Toggle the underpass layer, then the ask | "Terrain could not find Delhi's blackspots. OSM's underpass tags could. Give us raw radar and municipal drainage, and this gets substantially better." |

---

## The three questions most likely to be asked

**"Your CSI is low."**
> Yes — 0.13 on point-scale hourly heavy rain, and I will not dress that up.
> Nobody achieves high CSI on this task without radar. What matters is the
> comparison on identical rows: persistence 0.049, raw GFS 0.015. We are 2.7×
> persistence and 8× the global physics model, and the honest skill-decay curve
> is on the Verification screen.

**"How do I know there's no leakage?"**
> Every forecast row carries both `issue_time` and `valid_time`. There is
> exactly one read path. An automated test shuffles and corrupts every future
> row and asserts the features at t are unchanged. It runs in `make preflight`.
> It has caught us once already — it failed when `issue_time` equalled
> `valid_time` everywhere, which meant the filter was doing nothing.

**"Can I try my own storm?"** — the Sandbox screen

> Yes. Choose the rainfall and InundaNet runs live on 148,776 real 100 m cells.
> Only the rain is yours; the terrain, the ward geometry and the exposure counts
> are real, and the response is flagged `is_forecast: false`.
>
> **Then show them the wall.** The trained booster's highest split on event
> rainfall is **25.3 mm**, so above that it is mathematically constant — 40 mm,
> 120 mm and 300 mm return byte-identical answers. The sandbox reads that
> boundary out of the model artefact and draws it on the response curve.
>
> Say it first, before a judge finds it: *"Our flood labels do not contain
> anything wetter than this, so past this line the model has no evidence and
> stops changing. We would rather show you the edge of what we know than sell
> you a slider that does nothing."*
>
> Within the range it does have evidence, it moves properly: **8 → 11 → 17 → 23**
> high-risk wards across the four presets, and antecedent rain moves it further
> because saturated ground is the real second variable.

**"Why not bias-correct the rainfall so it handles cloudbursts?"**

> We built the quantile map and then found it cannot help *this* model. Quantile
> mapping is monotone, and a decision tree splits on order — so mapping
> InundaNet's rain *inputs* yields the identical tree with rescaled thresholds.
> It relabels the axis; it does not widen the response.
>
> It genuinely helps **RainCast**, where the compressed quantity is the
> *target*: ERA5 gave 20.9 mm on 28 Jun 2024 where IMD's gauge grid said 150.7,
> so the model has never been shown a cloudburst as a positive. That is why the
> 15 mm/h head had 63 test positives and was dropped.

**"Is the AI doing the forecasting?"**
> No. Three LightGBM models do the forecasting. The narration layer is a
> template that can only interpolate fields present in the model's own JSON —
> it is structurally incapable of inventing a figure. When an LLM is used, every
> number it writes is checked against the input and the output is rejected if it
> invents one.
