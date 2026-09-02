# PRAVAAH — evaluation figures

Regenerate everything with one command:

```bash
python eval/make_figures.py
```

Each figure is written twice: **PNG at 300 dpi** (slides, printing) and **PDF**
(vector, scales to any poster size). Every number is read from `reports/*.json`
or recomputed from the model itself — nothing is typed in by hand, so the deck
and the `/verify` screen cannot drift apart.

| # | File | What it shows | Use it for |
|---|---|---|---|
| 1 | `fig01_scorecard` | All three models, headline skill, baselines, margins | **The one slide.** Put this up first. |
| 2 | `fig02_raincast_vs_baselines` | RainCast vs persistence vs raw NWP on all 12 heads | The nowcast argument |
| 3 | `fig03_raincast_confusion` | Confusion matrices for the four shipped heads | "Show me the errors" |
| 4 | `fig04_reliability` | Calibration — does 30 % mean 30 %? | Probabilistic honesty |
| 5 | `fig05_ablation` | Which inputs earn their place | Why fusion, and the NWP gap |
| 6 | `fig06_rainfuse` | IMD official categories, CSI and Brier vs raw NWP | The gauge-anchored model |
| 7 | `fig07_inundanet_pr_confusion` | PR curve vs terrain baseline + confusion matrix | **The strongest ML result** |
| 8 | `fig08_inundanet_features` | What InundaNet actually uses | The underpass story |

## Three things to be ready to say

**"Your CSI is low."** Yes — 0.12 on point-scale hourly heavy rain, and figure 3
shows the false alarms rather than hiding them. Nobody achieves high CSI on this
task without radar. The claim is the comparison on identical rows: persistence
0.049, raw GFS 0.015.

**"Raw NWP scores zero on some heads — is that broken?"** No, and figure 2 labels
it. At 10 mm/h point scale the global models made **exactly zero hits** while
still producing 145 false alarms. That is a real limitation of coarse physics at
convective scales. We do **not** count those as wins — the headline is 6 of 7
heads where the physics scores at all, not 10 of 12.

**"Is InundaNet just detecting cities?"** That was the first version's failure —
imperviousness alone scored ROC-AUC 0.867. Figure 7 uses spatial-block
cross-validation so no training cell sits beside its own test cell, coordinates
and label-process columns are excluded as features, and the matched-negative
rescore is in `reports/inundanet_metrics.json`.

## What is deliberately not here

No skill-vs-lead curve. Open-Meteo's `previous_dayN` does not behave as an N-day
lead — measured correlation 0.579 / 0.566 / 0.594 at 24/48/72 h, with the
longest lead scoring *best*, which is impossible for genuine leads. See
`reports/skill_by_lead.json`. We would rather show one fewer chart than one
wrong one.
