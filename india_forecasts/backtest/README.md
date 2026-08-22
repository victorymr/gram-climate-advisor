# District-level ensemble backtest

Measures the **skill of the district forecasts** the advisor shows — the multi-model
mean anomalies and, especially, the **ensemble threshold odds** — by re-running the
same district collapse over historical initializations and scoring against observations.

Self-contained under `india_forecasts/backtest/`; nothing here touches the advisor app.

## Return-on-investment principle

**One download = one init date = every district x every lead-week (1-5) x every ensemble
member.** A single hindcast already gives full national coverage (666 districts / 6 zones),
all leads, and the full ensemble *for free*. The only axis a download can't buy is the
**climate state** — the year-to-year monsoon/ENSO condition and the season. So the ~50-init
budget is spent spanning *conditions*, never near-duplicate dates.

**Storage stays tiny by design:** download one init -> region-collapse to 666 districts
(reusing the weight tensor) -> keep the small collapsed member array -> **delete the raw**.
Permanent footprint is ~a few MB/init; transient peak is one init's raw download.

## Models & window

- **GEFS** — operational GEFSv12, **full 31-member** ensemble to +35 days, from
  `s3://noaa-gefs-pds` via Herbie (region + variable `.idx` byte-range subsetting).
  The 31-member/35-day archive starts 2020-09, so the clean window is **2021-2025**.
- **CFSv2** — operational archive `s3://noaa-cfs-pds`, capped to 1-2 members (00Z [+12Z]) to
  bound its cost (no region subsetting -> heavier per init).

## Sampling (`sample_inits.py` -> `inits.csv`)

50 00Z inits = 5 seasons x 10 slots (2 pre-monsoon, 7 monsoon JJAS ~biweekly, 1 withdrawal).
Condition spread over 2021-2025: La Nina normal (2021), La Nina surplus (2022),
**El Nino deficit (2023)**, La Nina surplus (2024), neutral (2025). ENSO/monsoon tags are
carried in `inits.csv` for stratified analysis (context, not truth).

## Truth (verification)

- **Rainfall** — IMD 0.25 deg gridded via `imdlib` (same source as `observed_departures.py`).
- **Temperature** — IMD gridded temperature (1 deg) via `imdlib`.
Both collapsed to districts and turned into weekly observed anomalies vs a fixed DOY normal.
Forecast anomalies use the operational ERA5 weekly climatology (what the app actually shows),
so **anomaly correlation** (bias-robust) is the headline deterministic score and **bias** is
reported separately as a model-vs-IMD offset diagnostic.

## Metrics (stratified by lead-week x variable x zone x climate-state)

- **Deterministic (MME mean):** anomaly correlation (ACC), RMSE, RMSE skill score vs
  climatology, bias.
- **Probabilistic (the ensemble — the point of the test):** CRPS / **CRPSS** vs climatology,
  **Brier score + Brier skill score for the app's actual thresholds** (wetter/drier tercile,
  heavy rain, dry spell, hot week), **reliability diagrams**, ROC/AUC, and a **rank histogram**
  (spread-skill). Baselines: climatology and persistence, so every number is a skill score.

## Layout

```
backtest/
  README.md            this file
  sample_inits.py      -> inits.csv (the 50 sampled inits + condition tags)
  inits.csv
  run_backtest.py      per init: download -> collapse to districts -> delete raw -> store
  build_truth.py       IMD rainfall + temp -> district weekly observed anomalies
  metrics.py           ACC/RMSE/CRPS(S)/Brier(SS)/reliability/rank-histogram
  rereference.py       re-reference collapsed forecasts to each model's own climatology
  plot_skill.py        skill-vs-lead plots (RMSE, BSS, before/after re-referencing)
  mme_weights.py       GEFS:CFSv2 weight sweep (-> MME_WEIGHTS in forecast_region_s2s.py)
  ec46_backtest.py     EC46 reforecast (2004-20) deterministic + ensemble skill
  plot_compare.py      three-model skill comparison
  bias_check.py        does model bias survive own-history referencing?
  build_calibration.py reliability curves per threshold event x lead -> ../../data/calibration.json
  build_skill.py       per lead-week x zone skill + confidence tiers   -> ../../data/forecast_skill.json
  collapsed/           kept per-init district member anomalies (small; git-ignored)
  truth/               kept per-valid-week district observed anomalies (small; git-ignored)
  scores/              output score tables
  plots/               skill-vs-lead, reliability diagrams, etc.
```

## Measured cost per init (2023-07-12, verified end-to-end)

| model | transient download (deleted) | runtime | kept (collapsed) |
|-------|------------------------------|---------|------------------|
| GEFS (31 mem, 6-hourly) | +16 MB | **~43 min** | 1.7 MB |
| CFSv2 (1-2 mem) | ~150 MB | ~5-10 min (est) | <1 MB |
| district collapse (both) | — | ~40 s | — |

**The binding constraint is request latency, not disk.** GEFS = 31 members x ~140
six-hourly steps ~= 1085 small S3 fetches at ~2.4 s each. Members are fetched
sequentially and GEFS APCP is delivered in **6-hourly buckets** (all needed to sum
weekly precip), so the 6-hourly cadence can't be coarsened without breaking rainfall.
=> ~43 min/init x 50 ~= **36 h** for GEFS alone (plus CFSv2). Kept total ~100 MB.

**Parallelizing members does NOT help** (measured): 6 concurrent members took 62 min and
dropped 3 members, vs 43 min / all-31 sequential. cfgrib decoding is GIL-bound so threads
don't overlap the real work, and concurrent members trigger AWS throttling. So GEFS is
pinned to AWS and fetched sequentially (`--workers 1`, the default). Real levers to cut the
36 h are therefore (a) fewer inits or (b) fewer members -- both trade coverage/fidelity.
The harness is **idempotent** (skips completed inits), so a long run can be interrupted and
resumed freely -- the most practical path is to just let the sequential run chip through.

Encoding note: Herbie prints a unicode status glyph that crashes on Windows' cp1252
console and silently stalls the fetch threads — the harness sets `PYTHONIOENCODING=utf-8`
for its subprocesses to avoid this.

## Reuse (not rewritten)

- `forecast_region.py`: `gadm_districts`, `region_weights` (district weight tensor).
- `forecast_region_s2s.py`: `anomalise`, `resolve_geom`, `regional_series`, `compute_probs`,
  threshold constants, `to_weekly`.
- `observed_departures.py`: IMD access pattern via `imdlib` + district collapse.
- `build_era5_clim.py`: ERA5 weekly climatology for forecast anomalies.
- `download_gefs.py` / `download_cfsv2.py`: model fetch (called per historical init).

## Run

```bash
python backtest/sample_inits.py                 # (re)write inits.csv
python backtest/run_backtest.py --limit 1       # measure/one-init smoke
python backtest/run_backtest.py                 # all 50 (idempotent; skips done inits)
python backtest/build_truth.py                  # IMD truth for the valid weeks
python backtest/rereference.py                  # own-climatology reference -> collapsed_reref/
BACKTEST_COLL=backtest/collapsed_reref python backtest/metrics.py   # scores/
python backtest/plot_skill.py                   # plots/
python backtest/build_calibration.py            # -> data/calibration.json (odds calibration)
python backtest/build_skill.py                  # -> data/forecast_skill.json (confidence tiers)
```

## What feeds the app

- `data/calibration.json` — maps each raw ensemble probability (per threshold event x lead) to
  how often it verified; applied to the Source Data odds.
- `data/forecast_skill.json` — per variable x lead-week x climate zone: ACC, RMSESS, a
  High/Medium/Low tier (ACC >= 0.5 / >= 0.3 / below) and the verified rate of each displayed
  category vs chance. Drives the per-week outlook confidence and the scenario confidence
  (`src/skill.py`, `src/rules.py`). Scores the MME_WEIGHTS-weighted GEFS+CFSv2 blend the app
  ships; EC46 joins the live blend but has no 2021-25 reforecast (its 2004-20 skill is recorded
  under `models` for comparison).
