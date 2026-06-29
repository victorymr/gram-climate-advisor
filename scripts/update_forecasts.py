#!/usr/bin/env python3
"""
Admin script to update district forecast data from CSV to JSON format.
This script converts the admin_forecast_template.csv into the district_forecasts.json
file used by the main application.
"""

import pandas as pd
import json
from datetime import datetime

def csv_to_json(csv_file='data/admin_forecast_template.csv', 
                json_file='data/district_forecasts.json'):
    """
    Convert CSV forecast data to JSON format.
    
    Args:
        csv_file (str): Path to the input CSV file
        json_file (str): Path to the output JSON file
    """
    
    try:
        # Read CSV file
        df = pd.read_csv(csv_file)
        
        # Convert DataFrame to list of dictionaries
        forecasts = []
        
        for _, row in df.iterrows():
            # Handle data type conversions safely
            rainfall_14d = row['rainfall_last_14_days_pct_departure']
            try:
                rainfall_14d = int(rainfall_14d)
            except (ValueError, TypeError):
                rainfall_14d = 0  # Default value if conversion fails
            
            # Handle boolean conversions
            heat_warning = str(row['heat_wave_warning']).lower() == 'true'
            heavy_rain = str(row['heavy_rain_warning']).lower() == 'true'
            
            forecast = {
                "state": row['state'],
                "district": row['district'],
                "forecast_date": str(row['forecast_date']),
                "rainfall_since_june_1_pct_departure": int(row['rainfall_since_june_1_pct_departure']),
                "rainfall_last_7_days_pct_departure": int(row['rainfall_last_7_days_pct_departure']),
                "rainfall_last_14_days_pct_departure": rainfall_14d,
                "monsoon_onset_status": row['monsoon_onset_status'],
                "week1_rainfall_signal": row['week1_rainfall_signal'],
                "week2_rainfall_signal": row['week2_rainfall_signal'],
                "week3_4_rainfall_signal": row['week3_4_rainfall_signal'],
                "seasonal_monsoon_context": row['seasonal_monsoon_context'],
                "tmax_signal": row['tmax_signal'],
                "tmin_signal": row['tmin_signal'],
                "heat_wave_warning": heat_warning,
                "heavy_rain_warning": heavy_rain,
                "humidity_heat_index_signal": row['humidity_heat_index_signal'],
                "imd_source_notes": row['imd_source_notes']
            }
            forecasts.append(forecast)
        
        # Write JSON file
        with open(json_file, 'w') as f:
            json.dump(forecasts, f, indent=2)
        
        print(f"✅ Successfully converted {len(forecasts)} district forecasts")
        print(f"📁 Input: {csv_file}")
        print(f"📁 Output: {json_file}")
        
        # Show summary
        print(f"\n📊 Summary:")
        states = list(set(f['state'] for f in forecasts))
        print(f"   - States: {len(states)} ({', '.join(states)})")
        print(f"   - Districts: {len(forecasts)}")
        
        # Show risk distribution
        heat_warnings = sum(1 for f in forecasts if f['heat_wave_warning'])
        rain_warnings = sum(1 for f in forecasts if f['heavy_rain_warning'])
        print(f"   - Heat wave warnings: {heat_warnings}")
        print(f"   - Heavy rain warnings: {rain_warnings}")
        
    except FileNotFoundError:
        print(f"❌ Error: File '{csv_file}' not found")
        print("   Make sure you're running this script from the project root directory")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def validate_forecast_data(json_file='data/district_forecasts.json'):
    """
    Validate the forecast JSON data for completeness and correct formats.
    
    Args:
        json_file (str): Path to the JSON file to validate
    """
    
    try:
        with open(json_file, 'r') as f:
            forecasts = json.load(f)
        
        print(f"\n🔍 Validating {json_file}...")
        
        required_fields = [
            'state', 'district', 'forecast_date', 'rainfall_since_june_1_pct_departure',
            'rainfall_last_7_days_pct_departure', 'rainfall_last_14_days_pct_departure',
            'monsoon_onset_status', 'week1_rainfall_signal', 'week2_rainfall_signal',
            'week3_4_rainfall_signal', 'seasonal_monsoon_context', 'tmax_signal',
            'tmin_signal', 'heat_wave_warning', 'heavy_rain_warning',
            'humidity_heat_index_signal', 'imd_source_notes'
        ]
        
        valid_values = {
            'monsoon_onset_status': ['not_started', 'delayed', 'normal', 'active', 'weak'],
            'week1_rainfall_signal': ['below_normal', 'near_normal', 'above_normal'],
            'week2_rainfall_signal': ['below_normal', 'near_normal', 'above_normal'],
            'week3_4_rainfall_signal': ['below_normal', 'near_normal', 'above_normal'],
            'seasonal_monsoon_context': ['below_normal_risk', 'normal', 'above_normal'],
            'tmax_signal': ['below_normal', 'near_normal', 'above_normal'],
            'tmin_signal': ['below_normal', 'near_normal', 'above_normal'],
            'humidity_heat_index_signal': ['low', 'normal', 'high']
        }
        
        errors = []
        warnings = []
        
        for i, forecast in enumerate(forecasts):
            # Check required fields
            for field in required_fields:
                if field not in forecast:
                    errors.append(f"Row {i+1}: Missing required field '{field}'")
            
            # Check valid values
            for field, valid_vals in valid_values.items():
                if field in forecast and forecast[field] not in valid_vals:
                    errors.append(f"Row {i+1}: Invalid value for '{field}': {forecast[field]} (should be one of {valid_vals})")
            
            # Check data types
            if 'heat_wave_warning' in forecast and not isinstance(forecast['heat_wave_warning'], bool):
                errors.append(f"Row {i+1}: heat_wave_warning should be boolean, got {type(forecast['heat_wave_warning'])}")
            
            if 'heavy_rain_warning' in forecast and not isinstance(forecast['heavy_rain_warning'], bool):
                errors.append(f"Row {i+1}: heavy_rain_warning should be boolean, got {type(forecast['heavy_rain_warning'])}")
            
            # Check date format
            if 'forecast_date' in forecast:
                try:
                    datetime.strptime(forecast['forecast_date'], '%Y-%m-%d')
                except ValueError:
                    errors.append(f"Row {i+1}: Invalid date format for forecast_date: {forecast['forecast_date']} (should be YYYY-MM-DD)")
        
        # Report results
        if errors:
            print(f"❌ Found {len(errors)} errors:")
            for error in errors[:10]:  # Show first 10 errors
                print(f"   - {error}")
            if len(errors) > 10:
                print(f"   ... and {len(errors) - 10} more errors")
        else:
            print("✅ No validation errors found")
        
        if warnings:
            print(f"⚠️  Found {len(warnings)} warnings:")
            for warning in warnings:
                print(f"   - {warning}")
        
        return len(errors) == 0
        
    except FileNotFoundError:
        print(f"❌ Error: File '{json_file}' not found")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON format - {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    print("🌾 Gram Climate Advisor - Forecast Update Tool")
    print("=" * 50)
    
    # Convert CSV to JSON
    csv_to_json()
    
    # Validate the generated JSON
    is_valid = validate_forecast_data()
    
    if is_valid:
        print(f"\n🎉 Forecast data is ready for use!")
        print(f"   You can now run the Streamlit app with: streamlit run app.py")
    else:
        print(f"\n⚠️  Please fix the validation errors before using the data")
