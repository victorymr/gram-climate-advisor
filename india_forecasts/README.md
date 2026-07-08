# India seasonal & subseasonal forecasts — download scripts

Scripts to pull **temperature** and **precipitation** forecasts and crop them to
an India bounding box, saved as NetCDF.

**Seasonal** (monthly means, leads 1–6+ months):

| Script | Model | Source | Auth |
|---|---|---|---|
| `download_seas5.py` | ECMWF **SEAS5** (and any C3S centre) | Copernicus CDS API | free account + token |
| `download_sfs.py` | NOAA **SFS Beta v1.0** | AWS S3 (NODD) | none (anonymous) |

**Subseasonal (S2S)** (weekly means, weeks 1–6):

| Script | Model | Source | Auth |
|---|---|---|---|
| `download_gefs.py` | NOAA **GEFS** (35-day, weeks 1–5) | AWS S3 via Herbie | none |
| `download_cfsv2.py` | NOAA **CFSv2** (to ~9 months) | AWS S3 (anonymous) | none |
| `download_ec46.py` | ECMWF **EC46** (46-day) | ECMWF ECDS `s2s-forecasts` | account + token |
| `download_ec46_openmeteo.py` | ECMWF **EC46** (live, no embargo) | Open-Meteo API | none |

Shared: `config.py` (bbox, variables, paths), `utils.py` (cropping/saving),
`s2s_utils.py` (weekly aggregation).

## Install
```bash
pip install -r requirements.txt
# GRIB support for SFS on Windows is easiest via conda:
#   conda install -c conda-forge cfgrib eccodes
```

## 1. ECMWF SEAS5 (Copernicus CDS)
One-time setup:
1. Register at https://cds.climate.copernicus.eu and log in.
2. Put your token in `~/.cdsapirc` (Windows: `C:\Users\<you>\.cdsapirc`) — format at
   https://cds.climate.copernicus.eu/how-to-api
3. Open the [dataset page](https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels)
   → **Download** tab → accept the licence once.

Run:
```bash
python download_seas5.py                                   # current init month, leads 1-6
python download_seas5.py --year 2026 --month 6 --leadtime 1 2 3 4 5 6
python download_seas5.py --centre ukmo --system 603        # a different C3S model
```
Output: `data/seas5/ecmwf51_YYYYMM_india.nc`.
Dataset `seasonal-monthly-single-levels`, `monthly_mean`, 1°×1°, init monthly, ~51 members.
**Units:** `2m_temperature` in K; `total_precipitation` is a **mean rate (m s⁻¹)** —
multiply by seconds-in-month for a monthly total.

Other C3S centres (same script, swap `--centre/--system`): `ecmwf/51`, `ukmo`,
`meteo_france`, `dwd`, `cmcc`, `ncep`, `jma`, `eccc`. Want a robust multi-model
mean? Pull several centres and average.

## 2. NOAA SFS Beta (AWS S3, no account)
SFS Beta launched **March 2026** and replaces CFSv2; layout is still settling, so
**explore first, then download:**
```bash
python download_sfs.py --explore                           # browse experiments/beta1/
python download_sfs.py --explore --prefix experiments/beta1/<cycle>/ --depth 2
python download_sfs.py --prefix experiments/beta1/<cycle>/.../ --pattern atm
python download_sfs.py --list-vars data/sfs/<file>.grib2   # see GRIB shortNames/units
```
- `experiments/beta1/` = NRT (31-member, monthly init, 12-month lead) + on-the-fly reforecasts (1991–2025).
- `experiments/phase_1/` = earlier hindcast prototypes (1994–2023, May/Nov inits).
- Files are global GRIB2; the script crops to India and writes `data/sfs/<file>_india.nc`.
- `--pattern` filters keys by substring (`atm`, `sfc`, a date, a member id);
  `--max-files` caps a run; `--download-only` skips the crop so you can inspect with `wgrib2`.

GRIB shortNames assumed: `2t` (2 m temp, K), `prate` (precip rate, mm s⁻¹). Confirm
with `--list-vars` and adjust `SFS_GRIB_SHORTNAMES` in `config.py` if your build differs.

## 3. Subseasonal (S2S) — weekly, weeks 1–6

Three models, all cropped to India and aggregated to **weekly means**, each saved as
`data/<model>/<model>_<YYYYMMDD>_india_weekly.nc`:

- vars: `t2m` (°C, weekly mean), `precip` (mm/day, weekly mean)
- dims: `(week, lat, lon)`; attrs: `model`, `init_date`
- ensemble-**mean** fields (members already collapsed — one field per week)

Weekly windows are fixed 7-day blocks from init: week 1 = forecast days 1–7, …,
week 5 = days 29–35 (`s2s_utils.to_weekly`). Temperature is a weekly mean; precip
accumulation buckets are summed then divided by 7 → a weekly mean rate in mm/day.

### Models

**NOAA GEFS — `download_gefs.py`** (35-day, weeks 1–5). Anonymous AWS S3 via Herbie's
GRIB index byte-range subsetting (small downloads); pulls the ensemble-mean `geavg`
files, `TMP:2m` + `APCP:surface` only.
```bash
python download_gefs.py --date 2026-06-29                 # ensemble mean -> weekly India NetCDF
python download_gefs.py --date 2026-06-29 --inspect       # print one inventory, stop
python download_gefs.py --date 2026-06-29 --members all    # each member -> *_india_weekly_members.nc
```
APCP arrives in accumulation buckets (summed per week by default); pass
`--precip-accum cumulative` if your build serves run-accumulated APCP.

`--members all` (c00 + p01..p30) writes a **member-resolved** weekly file
`data/gefs/gefs_<date>_india_weekly_members.nc` (dims `member,week,lat,lon`) — the ensemble used
for probabilistic odds below. It is **resumable**: each member is saved as it lands (cached members
skipped, transient AWS resets retried, then reassembled), so a capped or interrupted run can just be
rerun to continue. Fetching all members is sequential and slow (~30 subsets × 31 members).

**NOAA CFSv2 — `download_cfsv2.py`** (daily, runs to ~9 months, easily covers weeks 1–6).
Anonymous AWS S3 (`noaa-cfs-pds`), GRIB2, ~0.5°. Operationally one member per cycle (the
4 daily cycles form a lagged ensemble); pulls the 00 UTC member 01. The bucket layout
shifts occasionally, so **explore before you download**:
```bash
python download_cfsv2.py --date 2026-06-29 --explore      # show the S3 tree
python download_cfsv2.py --date 2026-06-29                # -> weekly India NetCDF
```

**ECMWF EC46 — `download_ec46.py`** (46-day extended ensemble). Lives in the ECMWF Data
Store (ECDS) `s2s-forecasts` dataset (the anonymous open-data ENS stops at 15 days). Needs
an ECDS token in `~/.ecdsapirc` and a one-time licence accept; temperature and precip are
**separate requests** (different lead-time encodings — see the script header).
```bash
python download_ec46.py --date 2026-05-24 --inspect       # tiny probe, print structure
python download_ec46.py --date 2026-05-24                 # -> weekly India NetCDF
python download_ec46.py --date 2026-05-24 --reforecast    # matching reforecast climatology
```
> **Embargo:** real-time S2S is delayed ~3 weeks. To combine EC46 with GEFS/CFSv2 at a
> single init, use a **matched older init** for all models, or take the live Open-Meteo
> route below. Reforecasts have no embargo.

**ECMWF EC46 (live) — `download_ec46_openmeteo.py`**. The no-embargo alternative: the
Open-Meteo API over an India grid (a point API sampled on a regular grid, then reshaped to
`(week, lat, lon)`; values already in °C and mm). Confirm the endpoint/variable names first:
```bash
python download_ec46_openmeteo.py --probe                 # confirm API shape, stop
python download_ec46_openmeteo.py --res 0.5 --forecast-days 46
```

### Anomalies need a common climatology — `build_era5_clim.py`

Operational forecasts don't ship their own climatology, so weekly anomalies use a shared
**ERA5** reference (every model anomalised the same way). Two stages:

1. **Day-of-year climatology** (built once): daily ERA5 2 m temp + precip over India for a
   reference period, averaged by day-of-year and lightly smoothed →
   `data/clim/era5_doy_clim_india.nc`.
2. **Per-init weekly climatology**: average the DOY clim over each forecast week's valid
   days → `data/clim/era5_weekly_init<MMDD>_india_weekly.nc`.

```bash
python build_era5_clim.py --build-doy --years 1991 2020    # stage 1 (one-time; needs ~/.cdsapirc)
python build_era5_clim.py --date 2026-06-29                # stage 2 for this init
```
GEFS/CFSv2 have no operational climatology of their own and rely on this common ERA5 clim;
EC46 additionally offers its own `--reforecast` climatology.

### Maps

```bash
python plot_s2s_multi.py --auto --common-clim data/clim/era5_weekly_init0629_india_weekly.nc
python plot_s2s_multi.py --auto --absolute                 # raw weekly means (no clim)
python plot_s2s_compare.py                                 # EC46 vs GEFS, per-model reforecast anomalies
```
`plot_s2s_multi.py` places N models side by side (rows = overlapping weeks, cols = models);
`plot_s2s_compare.py` is the two-model EC46-vs-GEFS view. Both default to anomalies when a
climatology is available and fall back to absolute otherwise.

### District / state time series — `forecast_region_s2s.py`

The subseasonal analogue of `forecast_region.py`. It collapses each model's weekly anomaly
grid to a region (cosine-latitude weighted over the GADM level-2 polygon, nearest-cell
fallback for districts smaller than a grid cell) and averages the available models into one
**multi-model mean** per week:
```bash
python forecast_region_s2s.py                              # districts in the default list
python forecast_region_s2s.py --init 20260629
python forecast_region_s2s.py --districts /path/to/district_coordinates.csv
python forecast_region_s2s.py --init 20260629 --probs      # also emit weekly threshold odds
```
Output `plots/s2s_region_weekly.csv` — **long format**, one row per district/week/model with
`model` ∈ {each model, `MME`}: `precip_anom_mm_day`, `t2m_anom_degC`, `n_models`. The `MME` rows are
the multi-model mean; the per-model rows drive the advisor's Source Data source-switcher.

**Probabilistic odds** — with `--probs` (auto-on when a `*_members.nc` file exists) it also writes
`plots/s2s_region_probs.csv`: per district/week the **fraction of GEFS ensemble members** crossing
each threshold — `p_wetter`/`p_near`/`p_drier` (±1 mm/day), `p_heavy` (≥ +7 mm/day), `p_dryspell`
(≤ −3 mm/day), `p_hot` (≥ +1.5 °C) — plus `n_members`. Thresholds are tied to the advisor's
`rules.py` for consistency.

Both CSVs are what the Gram Climate Advisor imports (its `scripts/import_model_forecasts.py`) to fill
the weekly forecast fields, the per-source values, and the ensemble odds.

### Helpers — `s2s_utils.py`

`to_weekly(da, method=...)` collapses a lead-resolved array into weekly windows (`mean` for
temperature, `sum_per_day` for precip buckets); `weekly_anomaly(fc, clim)`; `overlap_weeks(...)`;
`weekly_clim_for_init(doy_clim, init, weeks)`.

## India bounding box
Set in `config.py`. Default `INDIA_BBOX` (N 38 / S 6 / W 66 / E 98) covers mainland +
Andaman & Nicobar + Lakshadweep. `INDIA_BBOX_MAINLAND` is a tighter mainland-only box.

## Notes / extending
- **Subseasonal:** implemented — see [Subseasonal (S2S)](#3-subseasonal-s2s--weekly-weeks-16)
  above (GEFS / CFSv2 / EC46 → weekly NetCDF → `forecast_region_s2s.py`). To add another S2S
  source, aggregate it to a weekly India NetCDF (`t2m` °C, `precip` mm/day; dims `week,lat,lon`)
  with `s2s_utils.to_weekly` and it drops straight into the plots and the regional producer.
- **Multi-model:** NMME (IRI Data Library OPeNDAP) is a strong addition and supports
  server-side India subsetting — easy to add as a third script on request.
- These scripts download and crop only; anomaly/skill calc and plotting are left to
  your own analysis.

## Plotting (anomaly by default)
`plot_seas5.py` maps the ensemble mean as **anomalies vs the model's hindcast
climatology** by default (more informative than raw values for a forecast signal).

One-time, per init month — download the reforecast climatology, then plot:
```bash
python download_seas5.py --hindcast --month 6          # 1993-2016 June-init clim (~15-30 MB)
python plot_seas5.py                                    # -> plots/seas5_<YYYYMM>_{t2m,precip}_anom.png
python plot_seas5.py --absolute                         # raw maps instead
```
- Climatology defaults to the 1993-2016 reference period; change with `--ref-years START END`.
- `plot_seas5.py` auto-detects the matching `*clim*init<MM>*.nc`; or pass `--clim <file>`.
- Anomaly maps use diverging scales centered on zero (RdBu_r for temp, BrBG for precip);
  absolute maps use sequential scales (RdYlBu_r, YlGnBu).
