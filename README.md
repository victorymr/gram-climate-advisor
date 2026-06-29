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
│   └── update_forecasts.py        # CSV to JSON conversion script
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
