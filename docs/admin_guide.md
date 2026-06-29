# Admin Guide - Gram Climate Advisor

## Overview
This guide explains how to update the climate forecast data for the Gram Climate Advisor application.

## Update Process

### 1. Update the CSV File
Edit `data/admin_forecast_template.csv` with the latest forecast data:

**Required Columns:**
- `state`: State name (e.g., "Bihar")
- `district`: District name (e.g., "Gaya") 
- `forecast_date`: Date in YYYY-MM-DD format
- `rainfall_since_june_1_pct_departure`: Percentage departure from normal (negative = below normal)
- `rainfall_last_7_days_pct_departure`: Last 7 days rainfall departure
- `rainfall_last_14_days_pct_departure`: Last 14 days rainfall departure
- `monsoon_onset_status`: "not_started", "delayed", "normal", "active", or "weak"
- `week1_rainfall_signal`: "below_normal", "near_normal", or "above_normal"
- `week2_rainfall_signal`: "below_normal", "near_normal", or "above_normal"
- `week3_4_rainfall_signal`: "below_normal", "near_normal", or "above_normal"
- `seasonal_monsoon_context`: "below_normal_risk", "normal", or "above_normal"
- `tmax_signal`: "below_normal", "near_normal", or "above_normal"
- `tmin_signal`: "below_normal", "near_normal", or "above_normal"
- `heat_wave_warning`: "true" or "false"
- `heavy_rain_warning`: "true" or "false"
- `humidity_heat_index_signal`: "low", "normal", or "high"
- `imd_source_notes`: Free text description of sources

### 2. Convert to JSON
Run the update script:

```bash
# Activate virtual environment
source venv/bin/activate

# Convert CSV to JSON
python scripts/update_forecasts.py
```

This will:
- Convert the CSV to JSON format
- Validate the data for completeness
- Update `data/district_forecasts.json`

### 3. Test the Application
Start the Streamlit app to verify updates:

```bash
streamlit run app.py
```

## Data Sources

### Primary Sources (Tier 1)
- **IMD/Mausam**: Daily weather warnings, district warnings, heat-wave guidance
- **IMD Agromet Advisory**: District-level agromet advisories, state bulletins

### Secondary Sources (Tier 2)
- **ICAR/CRIDA**: District agriculture contingency plans
- **KVK/State Universities**: Local crop varieties, sowing windows

### Tertiary Sources (Tier 3)
- **NDMA**: Heat-wave guidelines
- **State Heat Action Plans**: State-specific heat response
- **NCDC/Ministry of Health**: Heat-health guidance

## Validation Rules

The script automatically checks for:
- Required fields present
- Valid value ranges
- Correct data types (boolean for warnings)
- Proper date format (YYYY-MM-DD)

## Adding New Districts

1. Add a new row to the CSV with the district's data
2. Add the district to `data/district_metadata.csv`
3. Run the update script
4. Optionally add ICAR contingency data to `data/icar_contingency_actions.json`

## Emergency Updates

For urgent updates during extreme weather events:
1. Update the CSV with latest warnings
2. Run the conversion script
3. Verify the advisory output shows correct risk levels

## Schedule

**Recommended Update Frequency:**
- **Normal conditions**: Weekly updates
- **Active monsoon/heat events**: Daily updates
- **Off-season**: Bi-weekly updates

## Troubleshooting

### Common Issues

**"File not found" error**
- Ensure you're running the script from the project root directory
- Check that the CSV file exists in `data/` folder

**Validation errors**
- Check that all required columns are present
- Verify values match the allowed options
- Ensure boolean fields are "true" or "false" (lowercase)

**Date format errors**
- Use YYYY-MM-DD format (e.g., "2026-06-27")
- Ensure dates are valid calendar dates

### Contact Support

For technical issues with the update process:
1. Check the validation output for specific error messages
2. Verify data against the format requirements
3. Test with a single district before bulk updates

## Data Quality Tips

1. **Cross-reference multiple sources** for rainfall and temperature data
2. **Document source changes** in the `imd_source_notes` field
3. **Review historical patterns** when setting seasonal context
4. **Validate against actual conditions** when possible
5. **Keep backup copies** of previous forecast data

## Security Considerations

- Store backup copies of forecast data
- Validate data before publishing to production
- Monitor for unusual data patterns that might indicate errors
- Maintain audit trail of data sources and update timestamps
