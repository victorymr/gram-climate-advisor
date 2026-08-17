# IMD Subseasonal & Seasonal Forecast Methods — One-Page Reference

*Compiled 2026-07-27 from IMD/MoES/IITM primary documents (links at each claim).*

## Extended-Range Forecast (ERF) — subseasonal, weeks 1–4

**System:** A multi-model ensemble of **4 CFSv2-based variants** — CFSv2 at T382 (~38 km), CFSv2 at
T126 (~100 km), and GFSbc (stand-alone GFS forced with bias-corrected CFSv2 SSTs) at both
resolutions — with **4 members each (1 control + 3 perturbed) = 16 members**. Developed at IITM Pune
under the Monsoon Mission, operational at IMD since **July 2016**. Atmospheric initial conditions
from NCMRWF, ocean ICs from INCOIS.
→ System document: [nwp.imd.gov.in/document_MME.pdf](https://nwp.imd.gov.in/document_MME.pdf)

**Cadence & products:** Runs weekly from every **Wednesday** IC, integrated 32 days; issued every
**Thursday** for four weekly windows (days 3–9, 10–16, 17–23, 24–30, each Fri–Thu). Weekly rainfall,
Tmax/Tmin and wind anomalies vs a CFSv2 **hindcast climatology** (2003–2015 originally; extended to
2003–2020 for 2021 onward). Targets the monsoon active–break cycle and MJO variability.
→ Products: [mausam.imd.gov.in/.../extendedrangeforecast.php](https://mausam.imd.gov.in/imd_latest/contents/extendedrangeforecast.php)
· IITM real-time: [tropmet.res.in/erpas](http://www.tropmet.res.in/erpas/)
· Agromet ERFS bulletin: [national_english_ERFS.php](https://mausam.imd.gov.in/imd_latest/contents/agromet/advisory/national_english_ERFS.php)

**Skill (official/peer-reviewed):** Useful all-India rainfall skill to **~3 weeks** (2–3 wks over
Central/NW India & monsoon zone; ~2 wks South Peninsula/NE/subdivision scale)
([Monsoon FAQ](https://mausam.imd.gov.in/imd_latest/monsoonfaq.pdf)). Monsoon-zone weekly rainfall
ACC ≈ **0.78 / 0.63 / 0.38 / 0.25** for weeks 1–4
([Sahai et al. 2021, Frontiers in Climate](https://doi.org/10.3389/fclim.2021.655919)).

## Long-Range Forecast (LRF) — seasonal monsoon (JJAS)

**Two tracks, revised 2021.** Since 2003 the LRF is issued in two stages (April; update late May).
From **2021** IMD's strategy pairs:
1. **Statistical Ensemble Forecasting System (SEFS, 2007)** — 8 lagged ocean/land/circulation
   predictors (e.g. Niño-3.4 tendency, SE Indian Ocean SST, N Atlantic MSLP); forecast = ensemble
   of the best of all 2ⁿ−1 predictor-subset models via multiple & projection-pursuit regression
   (Rajeevan, Pai et al. 2007, [Climate Dynamics 28:813](https://link.springer.com/article/10.1007/s00382-006-0197-6)).
2. **Dynamical Multi-Model Ensemble** — coupled global models from several centres anchored by
   **MMCFS** (Monsoon Mission CFS: NCEP CFSv2 modified by IITM; GFS atmosphere + MOM4 ocean,
   T382, v2 at T574) ([Monsoon Mission model page](https://monsoon-mission.tropmet.res.in/model/CFS-Climate-Forecast-System);
   [MMCFS v2 in GMD 2024](https://gmd.copernicus.org/articles/17/709/2024/)).

**Products:** April — all-India JJAS rainfall as **% of LPA (±5% error)** + tercile/5-category
probabilities and spatial tercile maps. Late May — update, **four homogeneous regions** + Monsoon
Core Zone probabilities, June monthly outlook, **onset over Kerala**. Monthly updates through the
season. LPA rebased to **87 cm (1971–2020)**; categories: Deficient <90%, Below 90–95%, Normal
96–104%, Above 105–110%, Excess >110%.
→ Index: [seasonal_forecast.php](https://mausam.imd.gov.in/imd_latest/contents/seasonal_forecast.php)
· Example releases: [2021 LRF](https://mausam.imd.gov.in/backend/assets/press_release_pdf/lrfapr21_presrelease_15apr.pdf) ·
[2026 LRF (MoES)](https://www.moes.gov.in/static/uploads/2026/04/4ad0309a938c2363e35788f53db67f7b.pdf)

**Skill:** Mean absolute error of the seasonal forecast **6.25% of LPA (2007–2019, SEFS era)** vs
8.91% (1995–2006); MMCFS ISMR ACC ≈ 0.55 at 3–4-month lead
([FAQ](https://mausam.imd.gov.in/imd_latest/monsoonfaq.pdf); [Clim. Dyn. 2024](https://link.springer.com/article/10.1007/s00382-024-07284-1)).

## Institutions & access

**MoES Monsoon Mission**: IITM Pune develops the models (MMCFS, ERF); **IMD** issues operational
forecasts; **NCMRWF**/**INCOIS** supply atmosphere/ocean initial conditions. *Access note:* all of
the above are published as **PDF bulletins and static images — no public API or gridded download**
(model data by request to monsoon_mission@tropmet.res.in), which is why this project ingests global
model + IMD observed-gridded data instead of IMD's own forecast products.
