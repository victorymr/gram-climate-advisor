import json
import os
import pandas as pd
from typing import Dict, List, Any

# Anchor data paths to the repo root (parent of this src/ dir) so they resolve no
# matter what the current working directory is when Streamlit runs the app.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, 'data')

def load_district_data(state: str, district: str) -> Dict[str, Any]:
    """Load district forecast data from JSON file."""
    try:
        with open(os.path.join(_DATA, 'district_forecasts.json'), 'r', encoding='utf-8') as f:
            all_forecasts = json.load(f)
        
        # Find matching district
        for forecast in all_forecasts:
            if forecast['state'].lower() == state.lower() and forecast['district'].lower() == district.lower():
                return forecast
        
        # Return default if not found
        return get_default_forecast(state, district)
    
    except FileNotFoundError:
        return get_default_forecast(state, district)

def load_icar_data(state: str, district: str) -> Dict[str, Any]:
    """Load ICAR contingency data from JSON file."""
    try:
        with open(os.path.join(_DATA, 'icar_contingency_actions.json'), 'r', encoding='utf-8') as f:
            all_icar = json.load(f)
        
        # Find matching district
        for icar in all_icar:
            if icar['state'].lower() == state.lower() and icar['district'].lower() == district.lower():
                return icar
        
        # Return default if not found
        return get_default_icar_data(state, district)
    
    except FileNotFoundError:
        return get_default_icar_data(state, district)

def get_district_list() -> List[Dict[str, str]]:
    """Get list of all available districts."""
    try:
        with open(os.path.join(_DATA, 'district_metadata.csv'), 'r', encoding='utf-8') as f:
            df = pd.read_csv(f)
            return df.to_dict('records')
    except FileNotFoundError:
        # Return some default districts for MVP
        return [
            {"state": "Bihar", "district": "Gaya"},
            {"state": "Bihar", "district": "Patna"},
            {"state": "Uttar Pradesh", "district": "Varanasi"},
            {"state": "Uttar Pradesh", "district": "Lucknow"},
            {"state": "Maharashtra", "district": "Yavatmal"},
            {"state": "Maharashtra", "district": "Nagpur"},
            {"state": "Rajasthan", "district": "Jaipur"},
            {"state": "Rajasthan", "district": "Jodhpur"},
            {"state": "Andhra Pradesh", "district": "Anantapur"},
            {"state": "Andhra Pradesh", "district": "Kurnool"}
        ]

def get_default_forecast(state: str, district: str) -> Dict[str, Any]:
    """Return default forecast data for districts not in dataset."""
    return {
        "state": state,
        "district": district,
        "forecast_date": "2026-06-27",
        "rainfall_since_june_1_pct_departure": 0,
        "rainfall_last_7_days_pct_departure": 0,
        "rainfall_last_14_days_pct_departure": 0,
        "monsoon_onset_status": "normal",
        "week1_rainfall_signal": "near_normal",
        "week2_rainfall_signal": "near_normal",
        "week3_4_rainfall_signal": "near_normal",
        "seasonal_monsoon_context": "normal",
        "tmax_signal": "near_normal",
        "tmin_signal": "near_normal",
        "heat_wave_warning": False,
        "heavy_rain_warning": False,
        "humidity_heat_index_signal": "normal",
        "imd_source_notes": "Default data - please update with actual IMD forecast"
    }

def get_default_icar_data(state: str, district: str) -> Dict[str, Any]:
    """Return default ICAR data for districts not in dataset."""
    return {
        "state": state,
        "district": district,
        "source": "ICAR-CRIDA District Agriculture Contingency Plan",
        "source_url": "Official ICAR-CRIDA district plan URL",
        "local_sources": [
            "IMD Agromet advisory",
            "KVK advisory"
        ],
        "major_crops": ["rice", "maize", "pulses"],
        "scenarios": {
            "delayed_monsoon": {
                "crop_actions": [
                    "Delay sowing until adequate soil moisture is available",
                    "Use locally recommended short-duration varieties where appropriate"
                ],
                "livestock_actions": [
                    "Conserve fodder",
                    "Ensure drinking water availability"
                ],
                "local_override_notes": []
            },
            "early_season_dry_spell": {
                "crop_actions": [
                    "Assess germination and plant stand",
                    "Use protective irrigation if available"
                ],
                "livestock_actions": [
                    "Plan fodder supplementation",
                    "Protect water sources"
                ],
                "local_override_notes": []
            },
            "mid_season_break": {
                "crop_actions": [
                    "Use protective irrigation where available",
                    "Delay fertilizer application until rainfall resumes"
                ],
                "livestock_actions": [
                    "Plan fodder supplementation",
                    "Protect water sources"
                ],
                "local_override_notes": []
            },
            "terminal_drought": {
                "crop_actions": [
                    "Prioritize water for crops at critical reproductive stages",
                    "Avoid spending scarce irrigation on failed crops"
                ],
                "livestock_actions": [
                    "Prepare for fodder shortage",
                    "Protect drinking water sources"
                ],
                "local_override_notes": []
            },
            "excess_rainfall_waterlogging": {
                "crop_actions": [
                    "Clear drainage channels",
                    "Avoid field operations during heavy rain"
                ],
                "livestock_actions": [
                    "Move livestock away from flood-prone areas",
                    "Protect stored fodder"
                ],
                "local_override_notes": []
            }
        }
    }
