# Gram Climate Advisor 🌾

A simple web application that helps rural communities in India understand near-term weather and climate risks and take practical action.

## 🎯 Product Goal

Build a climate risk advisory system that translates official forecast signals and adaptation guidance into plain-language, district-level advisories for:

- **Heat stress / heat waves**
- **Delayed monsoon onset / delayed sowing** 
- **Early-season dry spell**
- **Mid-season monsoon break**
- **Terminal drought / early withdrawal risk**
- **Excess rainfall / waterlogging**

## 🏗️ Architecture

The system follows a strict 4-tier source hierarchy:

1. **Tier 1**: IMD/Mausum official forecasts and warnings
2. **Tier 2**: ICAR/CRIDA agricultural contingency plans  
3. **Tier 3**: Health, disaster, and community preparedness guidance
4. **Tier 4**: International adaptation references (background only)

## 🛰️ Model-based forecasts (subseasonal & seasonal)

By default the forecast fields are extracted by hand from IMD imagery (see **Admin Updates** below).
The advisor can instead be driven by **numerical model forecasts** produced by the companion
`india_forecasts` pipeline (vendored in this repo at `india_forecasts/`), which pulls real subseasonal and
seasonal models and collapses them to each district.

### What the models provide

- **Subseasonal (weekly, weeks 1–4/5)** — a multi-model mean of **GEFS + CFSv2 + EC46** as weekly
  rainfall and temperature anomalies per district. EC46 (ECMWF's 46-day extended ensemble) is pulled
  **live from the Open-Meteo seasonal API** (no account, no ~3-week embargo, ~50 members); it joins the
  mean for any init it shares with the other models.
- **Weekly threshold odds** — genuine probabilities from the **ensemble members, pooled across every
  model** that posts members for the init (GEFS members and/or EC46's ~50 members): the chance of a
  wetter/drier-than-normal week, heavy rain, a dry spell, or a hot week. The contributing model(s) and
  member count are recorded alongside the odds.
- **Seasonal (monthly)** — a SEAS5 + SFS tercile signal distilled into `seasonal_monsoon_context`.

Model output **augments** the IMD data: the weekly *forecast* fields are replaced by the model
multi-model mean, while the *observed* IMD fields (rainfall departures, monsoon onset, official
heat/heavy-rain warnings — which models cannot provide) are **preserved**.

### Refresh (one command, from the advisor project root)

```bash
python scripts/run_forecast_pipeline.py                                # reprocess with existing model files
python scripts/run_forecast_pipeline.py --download --init 2026-06-29   # pull the models first
python scripts/run_forecast_pipeline.py --download --no-members        # skip the (slow) ensemble odds
```

The orchestrator runs the `india_forecasts` producers (ERA5 climatology → weekly multi-model CSV →
GEFS ensemble members → seasonal terciles), then the bridge, writing `data/district_forecasts.json`.
It is idempotent (skips stages whose outputs exist; `--force` rebuilds) and download-tolerant.

Under the hood:
- `scripts/import_model_forecasts.py` — the **bridge**: reads the `india_forecasts` outputs
  (`s2s_region_weekly.csv`, `s2s_region_probs.csv`, `forecast_<district>.csv`) and merges them into
  `district_forecasts.json`, preserving the IMD fields.
- `india_forecasts/forecast_region_s2s.py` — collapses the weekly model grids to each district
  (multi-model mean, per-model values, and per-member threshold probabilities).

### What the app shows

- **4-Week Outlook** — plain-language **categories** per week (e.g. *Slightly drier*, *Very warm*),
  with a note pointing to Source Data for the detail.
- **Source Data** — a **source switcher** (Multi-model mean · individual models, each with exact weekly
  values; *Official IMD guidance* appears only for the pilot districts that have hand-read IMD numbers,
  since IMD publishes no per-district numeric extended forecast), the **weekly threshold odds**, and a
  **nationwide map** at the bottom.
- **Nationwide map** — a country-wide choropleth of the same forecast, with the selected district
  outlined. Three dropdowns drive it: **variable** (Rainfall / Temperature / Season rainfall departure),
  **week** (1–4), and **data source** (MME / CFSv2 / EC46 / GEFS). The season-departure view is observed
  IMD data and labels its date range.
- Every "Week N" in the tables, odds, and map is labelled with the **actual valid dates** (e.g.
  *Week 1 · Jul 12–18*), derived from the init date.

The app pins its working directory to its own location on startup and reads all data via
repo-anchored paths, so `streamlit run app.py` works from any directory (the sidebar shows how many
districts loaded). The clickable map and choropleth need `streamlit-folium` (in `requirements.txt`).

Each district record gains three optional keys, all consumed by the app with graceful fallbacks:
- `forecast_variants` — the IMD / MME / per-model weekly values behind the source switcher.
- `weekly_probabilities` — the per-week threshold odds (fraction of ensemble members crossing each
  threshold), with the member count.
- `forecast_source` — a provenance string shown in the app.

If these keys are absent (e.g. a fresh IMD-only `district_forecasts.json` from `update_forecasts.py`),
the app falls back to the numeric outlook and hides the switcher/odds — so the model layer is fully
optional.

## 📁 Project Structure

```
gram-climate-advisor/
├── app.py                          # Main Streamlit application
├── requirements.txt                # Python dependencies
├── venv/                          # Virtual environment
├── data/                          # Data files
│   ├── district_forecasts.json    # District-level forecast data
│   ├── admin_forecast_template.csv # Admin update template
│   ├── district_metadata.csv      # District list
│   ├── icar_contingency_actions.json # ICAR contingency plans
│   └── crop_calendars.json        # District-specific crop calendars
├── src/                           # Core application logic
│   ├── utils.py                   # Data loading utilities
│   ├── rules.py                   # Scenario classification engine
│   └── advisory.py                # Advisory generation logic
├── scripts/                       # Admin and utility scripts
│   ├── update_forecasts.py        # IMD CSV -> district_forecasts.json
│   ├── import_model_forecasts.py  # Merge india_forecasts model output into district_forecasts.json
│   └── run_forecast_pipeline.py   # One command: run the whole model pipeline + refresh forecasts
├── india_forecasts/               # Vendored forecast pipeline (subseasonal & seasonal models)
│   ├── forecast_region_s2s.py     # Weekly multi-model + per-member odds per district
│   ├── forecast_region.py         # Seasonal tercile forecast per district
│   ├── download_*.py              # Model/obs downloaders (GEFS, CFSv2, EC46, SEAS5, SFS, ERA5)
│   ├── build_era5_clim.py         # ERA5 weekly climatology (for anomalies)
│   ├── config.py, utils.py, s2s_utils.py, requirements.txt, README.md
│   └── data/, plots/              # Generated/downloaded artifacts (git-ignored)
├── tests/                         # Test suite
│   └── test_scenarios.py          # Main scenario tests
└── docs/                          # Documentation
    └── admin_guide.md             # Admin update guide
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd gram-climate-advisor
   ```

2. **Create and activate virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   streamlit run app.py
   ```

5. **Open in browser**
   Navigate to `http://localhost:8501`

## 🧪 Testing

Run the test suite to verify the system is working correctly:

```bash
source venv/bin/activate
python tests/test_scenarios.py
```

The test suite covers:
- Scenario classification for all 6 risk types
- Advisory generation with real data
- Edge cases and error conditions

## 📊 Coverage

### Pilot Districts (MVP)

**Bihar**: Gaya, Patna
**Uttar Pradesh**: Varanasi, Lucknow  
**Maharashtra**: Yavatmal, Nagpur
**Rajasthan**: Jaipur, Jodhpur
**Andhra Pradesh**: Anantapur, Kurnool

### User Types Supported

- Farmers
- Livestock owners
- Outdoor workers
- Village officials
- NGO / extension workers
- Health workers

### Crop Information

The system includes district-specific crop calendars for:
- Major crops (rice, wheat, maize, cotton, etc.)
- Local varieties and sowing windows
- Growth stage timing
- Water requirements by stage
- Climate sensitivity ratings

## 🔧 Admin Updates

### Weekly Update Process

1. **Edit the CSV template**
   ```bash
   # Open data/admin_forecast_template.csv in your preferred spreadsheet editor
   # Update with latest IMD forecast data
   ```

2. **Convert to JSON**
   ```bash
   source venv/bin/activate
   python scripts/update_forecasts.py
   ```

3. **Validate and test**
   ```bash
   # The script automatically validates data format
   # Test the app with: streamlit run app.py
   ```

### Data Sources

**Primary (Tier 1)**:
- IMD daily weather warnings
- IMD Agromet advisory services
- Extended range and seasonal forecasts

**Secondary (Tier 2)**:
- ICAR-CRIDA district contingency plans
- KVK local agricultural advisories
- State agricultural universities

**Tertiary (Tier 3)**:
- NDMA heat-wave guidelines
- State heat action plans
- Ministry of Health guidance

For detailed instructions, see [docs/admin_guide.md](docs/admin_guide.md).

## 🎯 Features

### Risk Assessment

- **Overall risk level**: Low, Watch, Alert, Severe
- **Scenario classification**: 6 climate risk scenarios
- **Confidence scoring**: Based on data consistency
- **Multi-source validation**: Cross-reference official sources

### Advisory Output

- **Plain-language forecast summary**
- **Recommended actions**:
  - Do now (immediate actions)
  - Prepare (7-14 day planning)
  - Avoid (what not to do)
- **User-type specific guidance**
- **Source attribution and disclaimers**

### Technical Features

- **Rule-based scenario classification**
- **Transparent decision logic**
- **Modular action library**
- **Admin-friendly data updates**
- **Comprehensive test coverage**

## 🛡️ Guardrails

The system **does not** state:
- "The monsoon will fail"
- "Do not plant" 
- "This crop will fail"
- "This is official government advice"
- "This is medical advice"

The system **may** state:
- "Forecast signals suggest elevated risk of delayed sowing"
- "Consider waiting for adequate soil moisture before sowing"
- "Check local KVK or agriculture officer guidance"
- "Follow official IMD warnings and local government instructions"

## 📈 Success Criteria

The MVP is successful if:

- ✅ User can get district-level advisory in under 30 seconds
- ✅ Output clearly explains risk and recommended actions
- ✅ Scenario classification is transparent and auditable  
- ✅ App can be updated weekly with new forecast inputs
- ✅ Source hierarchy is clear and followed
- ✅ Structure supports future automation and multilingual delivery

## 🔮 Future Enhancements

**Version 0.2**:
- Local KVK/state agriculture override layer
- Health and village-official guidance layer
- Printable advisory format
- Source links integration

**Version 0.3**:
- Hindi/regional language support
- Map view interface
- Admin update interface
- Automated data ingestion
- SMS/WhatsApp-friendly summaries

## 🤝 Contributing

1. Follow the existing code structure and style
2. Add tests for new features
3. Update documentation for any changes
4. Ensure all tests pass before submitting

## 📄 License

This project is part of the ClimateAdapt initiative. See license file for details.

## 🆘 Support

For technical issues:
1. Check the test suite: `python tests/test_scenarios.py`
2. Review admin guide: [docs/admin_guide.md](docs/admin_guide.md)
3. Verify data format with validation script

For data source questions:
- Refer to the source hierarchy in this README
- Check IMD official sources for forecast data
- Consult ICAR-CRIDA for agricultural contingency plans

---

**Disclaimer**: This advisory system provides planning support based on official forecast data and agricultural contingency plans. Always follow local government instructions, official IMD warnings, and seek professional advice for critical decisions.
