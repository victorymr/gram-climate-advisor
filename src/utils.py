import json
import os
import pandas as pd
from difflib import get_close_matches
from typing import Dict, List, Any, Optional

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

# ICAR-CRIDA plans are from ~2012. Many districts have been renamed, split, or
# their romanization has changed. These maps bridge the forecast (current) names
# to the ICAR (vintage) names so the advisory can find the right contingency plan.

_STATE_ALIASES: Dict[str, str] = {
    "telangana": "Andhra Pradesh",
    "jammu and kashmir": "Jammu & Kashmir",
    "andaman and nicobar": "Andaman & Nicobar",
    "dadra and nagar haveli and daman and diu": "Daman & Diu",
}

_DISTRICT_ALIASES: Dict[str, str] = {
    # Andhra Pradesh — spelling variants
    "Visakhapatanam": "Visakhapatnam",
    "Spsr Nellore": "Nellore",
    "Y.S.R.": "Kadappa",
    # Arunachal Pradesh
    "Papum Pare": "Pamumpare",
    # Assam
    "Marigaon": "Morigaon",
    "Kamrup Metro": "Kamrup",
    "West Karbi Anglong": "Karbi Anglong",
    # Bihar
    "Begusarai": "Begusari",
    "Jehanabad": "Jehannabad",
    "Sheohar": "Shoehar",
    "Purnia": "Purnea",
    "Pashchim Champaran": "West Champaran",
    "Purbi Champaran": "East Champaran",
    "Kaimur (Bhabua)": "Kaimur",
    # Chhattisgarh
    "Gariyaband": "Gaiyaband",
    "Rajnandgaon": "Rajnandaon",
    "Janjgir-Champa": "Janjgir",
    "Korea": "Koriya",
    # Gujarat
    "Ahmadabad": "Ahmedabad",
    "Banas Kantha": "Banaskantha",
    "Chhotaudepur": "Chhota Udepur",
    "Dang": "Dangs",
    "Sabar Kantha": "Sabarkantha",
    "Mahesana": "Mehasana",
    "Kachchh": "Kutch",
    # Haryana
    "Gurugram": "Gurgaon",
    "Charki Dadri": "Bhiwani",
    "Nuh": "Gurgaon",
    # Himachal Pradesh
    "Lahul And Spiti": "Lahul & Spiti",
    # Jharkhand
    "East Singhbum": "East Singhbhum",
    "Giridih": "Giridh",
    "Palamu": "Palamau",
    "Sahebganj": "Sahibganj",
    "Saraikela Kharsawan": "Saraikela",
    "Khunti": "Ranchi",
    # Karnataka
    "Bagalkote": "Bagalkot",
    "Ballari": "Bellary",
    "Belagavi": "Belgaum",
    "Bengaluru Urban": "Bengaluru Rural",
    "Chamarajanagara": "Chamarajanagar",
    "Chikkaballapura": "Chickballapur",
    "Chikkamagaluru": "Chikmagalur",
    "Davangere": "Davanagere",
    "Mysuru": "Mysore",
    "Shivamogga": "Shimoga",
    "Tumakuru": "Tumkur",
    "Uttara Kannada": "Uttar Kannada",
    "Vijayapura": "Bijapur",
    "Vijayanagar": "Ballari",
    "Kalaburagi": "Gulbarga",
    # Madhya Pradesh
    "Barwani": "Badwani",
    "Chhindwara": "Chhindhwara",
    "Shahdol": "Shahadol",
    "East Nimar": "Khandwa",
    "Khargone": "West Nimar",
    "Niwari": "Tikamgarh",
    # Maharashtra
    "Nashik": "Nasik",
    "Mumbai": "Mumbai City",
    # Manipur
    "Senapati": "Senapathi",
    # Meghalaya
    "East Khasi Hills": "East Khasi HJills",
    "West Jaintia Hills": "West Jaintla Hills",
    "Eastern West Khasi Hills": "South West Khasi Hills",
    # Mizoram
    "Saiha": "Siaha",
    # Nagaland
    "Mokokchung": "Mokokcung",
    # Odisha
    "Anugul": "Angul",
    "Balangir": "Bolangir",
    "Jagatsinghapur": "Jagatsinghpur",
    "Jajapur": "Jajpur",
    "Kendujhar": "Keonjhar",
    "Khordha": "Khurdha",
    "Nabarangpur": "Nabarangapur",
    "Sonepur": "Sonapur",
    "Baleshwar": "Balasore",
    # Punjab
    "Ferozepur": "Ferozpur",
    "Rupnagar": "Ropar",
    "Shahid Bhagat Singh Nagar": "Shaid Bhagat Singh Nagar",
    "S.A.S Nagar": "Rupnagar",
    "Malerkotla": "Sangrur",
    # Rajasthan
    "Ganganagar": "Sriganganagar",
    "Jaipur Gramin": "Jaipur",
    "Jodhpur Gramin": "Jodhpur",
    # Tamil Nadu
    "Cuddalore": "Cuddalor",
    "Kanniyakumari": "Kanyuakumari",
    "Krishnagiri": "Krishnagir",
    "Pudukkottai": "Pudukkotai",
    "Sivaganga": "Sivagangai",
    "Tirunelveli": "Thirunelveli",
    "Tiruvannamalai": "Thiruvannamalai",
    "Villupuram": "Viluppuram",
    "The Nilgiris": "Nilgiris",
    "Kanchipuram": "Kancheerpuram",
    "Tuticorin": "Thoothukudi",
    "Chengalpattu": "Kancheerpuram",
    "Kallakurichi": "Viluppuram",
    "Ranipet": "Vellore",
    "Tirupathur": "Vellore",
    "Mayiladuthurai": "Nagapattinam",
    "Tenkasi": "Tirunelveli",
    # Uttar Pradesh
    "Ambedkar Nagar": "Ambedkarnagar",
    "Baghpat": "Bagpat",
    "Budaun": "Badaun",
    "Bulandshahr": "Bulandshahar",
    "Gautam Buddha Nagar": "Gaitam Budh Nagar",
    "Kasganj": "Kasgunj",
    "Kushi Nagar": "Kushinagar",
    "Rae Bareli": "Raebareli",
    "Saharanpur": "Shahranpur",
    "Sambhal": "Shambhal",
    "Sant Kabeer Nagar": "Santkabirnagar",
    "Shahjahanpur": "Shahjhanpur",
    "Siddharth Nagar": "Shiddarthnagar",
    "Ayodhya": "Faizabad",
    "Kheri": "Lakhimpur Kheri",
    "Bhadohi": "Varanasi",
    "Amroha": "Moradabad",
    "Kanpur Dehat": "Kanpur Nagar",
    "Prayagraj": "Allahabad",
    # Uttarakhand
    "Rudra Prayag": "Rudraprayag",
    "Udam Singh Nagar": "Udham Singh Nagar",
    "Uttar Kashi": "Uttarkashi",
    # West Bengal
    "Maldah": "Malda",
    "24 Paraganas North": "North 24 Parganas",
    "24 Paraganas South": "South 24 Parganas",
    "Medinipur East": "Purba Medinipur",
    "Medinipur West": "Paschim Medinipur",
    "Paschim Bardhaman": "Bardhaman",
    "Purba Bardhaman": "Bardhaman",
    "Dinajpur Dakshin": "Dakshin Dinajpur",
    "Dinajpur Uttar": "Uttar Dinajpur",
    "Jhargram": "Paschim Medinipur",
    "Kalimpong": "Darjeeling",
    "Kolkata": "North 24 Parganas",
    # Telangana (was part of AP in 2012 — map to AP ICAR entries)
    "Adilabad": "Adilabad",
    "Bhadradri Kothagudem": "Khammam",
    "Hanumakonda": "Warangal",
    "Hyderabad": "Ranga Reddy",
    "Jagitial": "Karimnagar",
    "Jangoan": "Warangal",
    "Jayashankar Bhupalapally": "Warangal",
    "Jogulamba Gadwal": "Mahabubnagar",
    "Kamareddy": "Nizamabad",
    "Karimnagar": "Karimnagar",
    "Khammam": "Khammam",
    "Kumuram Bheem Asifabad": "Adilabad",
    "Mahabubabad": "Warangal",
    "Mahabubnagar": "Mahabubnagar",
    "Mancherial": "Adilabad",
    "Medak": "Medak",
    "Medchal Malkajgiri": "Ranga Reddy",
    "Mulugu": "Warangal",
    "Nagarkurnool": "Mahabubnagar",
    "Nalgonda": "Nalgonda",
    "Narayanpet": "Mahabubnagar",
    "Nirmal": "Adilabad",
    "Nizamabad": "Nizamabad",
    "Peddapalli": "Karimnagar",
    "Rajanna Sircilla": "Karimnagar",
    "Ranga Reddy": "Ranga Reddy",
    "Sangareddy": "Medak",
    "Siddipet": "Medak",
    "Suryapet": "Nalgonda",
    "Vikarabad": "Ranga Reddy",
    "Wanaparthy": "Mahabubnagar",
    "Warangal": "Warangal",
    "Yadadri Bhuvanagiri": "Nalgonda",
    # J&K (ICAR uses "Jammu & Kashmir")
    "Srinagar": "Srinagar",
    "Jammu": "Jammu",
    "Anantnag": "Anantnag",
    "Baramulla": "Baramulla",
    "Doda": "Doda",
    "Kathua": "Kathua",
    "Kishtwar": "Doda",
    "Kulgam": "Anantnag",
    "Kupwara": "Baramulla",
    "Poonch": "Poonch",
    "Pulwama": "Srinagar",
    "Rajouri": "Poonch",
    "Ramban": "Doda",
    "Reasi": "Udhampur",
    "Samba": "Jammu",
    "Shopian": "Anantnag",
    "Udhampur": "Udhampur",
    "Bandipora": "Baramulla",
    "Budgam": "Srinagar",
    "Ganderbal": "Srinagar",
    # Ladakh (was part of J&K)
    "Kargil": "Leh",
    "Leh Ladakh": "Leh",
    # Delhi (no ICAR plan — use nearest agricultural district)
    "Central": "Ghaziabad",
    "East": "Ghaziabad",
    "New Delhi": "Ghaziabad",
    "North": "Ghaziabad",
    "North East": "Ghaziabad",
    "North West": "Rohtak",
    "Shahdara": "Ghaziabad",
    "South": "Gurgaon",
    "South East": "Gurgaon",
    "South West": "Gurgaon",
    "West": "Ghaziabad",
    # Andaman (ICAR has "Andaman & Nicobar")
    "Nicobars": "Nicobar",
    "North And Middle Andaman": "North & Middle Andaman",
    "South Andamans": "South Andaman",
    # Puducherry
    "Pondicherry": "Pondicherry",
    "Karaikal": "Pondicherry",
    "Mahe": "Pondicherry",
    "Yanam": "Pondicherry",
    # Sikkim
    "Gangtok": "East Sikkim",
    "Gyalshing": "West Sikkim",
    "Mangan": "North Sikkim",
    "Namchi": "South Sikkim",
    "Pakyong": "East Sikkim",
    "Soreng": "West Sikkim",
    # Andhra Pradesh — post-2012 splits mapped to parent districts
    "Alluri Sitharama Raju": "Visakhapatnam",
    "Anakapalli": "Visakhapatnam",
    "Annamayya": "Kadappa",
    "Bapatla": "Guntur",
    "Eluru": "West Godavari",
    "Kakinada": "East Godavari",
    "Konaseema": "East Godavari",
    "Nandyal": "Kurnool",
    "Ntr": "Guntur",
    "Palnadu": "Guntur",
    "Parvathipuram Manyam": "Srikakulam",
    "Sri Sathya Sai": "Anantapur",
    "Tirupati": "Chittoor",
    "Vizianagaram": "Srikakulam",
    # Arunachal Pradesh — post-2012 splits
    "Itanagar capital complex": "Pamumpare",
    "Kamle": "Lower Subansiri",
    "Kra Daadi": "Kurung Kumey",
    "Leparada": "Lower Subansiri",
    "Lower Siang": "West Siang",
    "Pakke Kessang": "East Kameng",
    "Shi Yomi": "West Siang",
    "Siang": "East Siang",
    # Assam — post-2012 splits
    "Bajali": "Barpeta",
    "Biswanath": "Sonitpur",
    "Charaideo": "Sivasagar",
    "Hojai": "Nagaon",
    "Majuli": "Jorhat",
    "South Salmara Mancachar": "Dhubri",
    "Tamulpur": "Baksa",
    # Chhattisgarh — post-2012 splits
    "Gaurella Pendra Marwahi": "Bilaspur",
    "Khairgarh Chhuikhadan Gandai": "Rajnandaon",
    "Manendragarh Chirimiri Bharatpur": "Koriya",
    "Mohla Manpur Ambagarh Chouki": "Rajnandaon",
    "Sakti": "Raigarh",
    "Sarangarh Bilaigarh": "Raigarh",
    # Gujarat — missing/renamed
    "Dohad": "Kheda",
    "Panch Mahals": "Kheda",
    # Madhya Pradesh — post-2012 splits/renames
    "Khargone": "Khandwa",
    "Narmadapuram": "Hoshangabad",
    # Maharashtra
    "Mumbai": "Mumbai City",
    "Mumbai Suburban": "Thane",
    # Manipur — post-2012 splits
    "Jiribam": "Imphal East",
    "Kakching": "Thoubal",
    "Kamjong": "Ukhrul",
    "Kangpokpi": "Senapathi",
    "Noney": "Tamenglong",
    "Pherzawl": "Churachandpur",
    "Tengnoupal": "Chandel",
    # Mizoram — post-2012 splits
    "Hnahthial": "Lunglei",
    "Khawzawl": "Champhai",
    "Saitual": "Aizawl",
    # Nagaland — post-2012 splits
    "Chumoukedima": "Dimapur",
    "Niuland": "Dimapur",
    "Noklak": "Tuensang",
    "Shamator": "Tuensang",
    "Tseminyu": "Kohima",
    # Rajasthan — post-2012 splits
    "Anoopgarh": "Sriganganagar",
    "Balotra": "Barmer",
    "Beawar": "Ajmer",
    "Deeg": "Bharatpur",
    "Didwana Kuchaman": "Nagaur",
    "Dudu": "Jaipur",
    "Gangapurcity": "Sawai Madhopur",
    "Kekri": "Ajmer",
    "Khairthal-Tijara": "Alwar",
    "Kotputli-Behror": "Jaipur",
    "Neem Ka Thana": "Sikar",
    "Phalodi": "Jodhpur",
    "Salumbar": "Udaipur",
    "Sanchor": "Jalore",
    "Shahpura": "Jaipur",
    # Tamil Nadu
    "Chennai": "Thiruvallur",
    # Punjab
    "Rupnagar": "Rogar",
    "S.A.S Nagar": "Rogar",
    # Sikkim
    "Mangan": "North Simmim",
    # J&K — PoK districts (no ICAR plan)
    "Mirpur": "Poonch",
    "Muzaffarabad": "Baramulla",
    # Dadra & Daman & Diu
    "Dadra And Nagar Haveli": "Daman",
    # Lakshadweep (no ICAR plan — use nearest)
    "Lakshadweep District": "Kavaratti",
}


def _resolve_icar_alias(state: str, district: str) -> tuple[str, str]:
    """Resolve (state, district) from forecast naming to ICAR naming."""
    state_lower = state.lower()
    resolved_state = _STATE_ALIASES.get(state_lower, state)
    resolved_district = _DISTRICT_ALIASES.get(district, district)
    return resolved_state, resolved_district


def load_icar_data(state: str, district: str) -> Dict[str, Any]:
    """Load ICAR contingency data from JSON file.

    Handles district name changes between the 2012 ICAR plans and current
    administrative boundaries via an explicit alias map plus fuzzy matching.
    """
    try:
        with open(os.path.join(_DATA, 'icar_contingency_actions.json'), 'r', encoding='utf-8') as f:
            all_icar = json.load(f)

        resolved_state, resolved_district = _resolve_icar_alias(state, district)

        # Pass 1: exact match on resolved name
        for icar in all_icar:
            if (icar['state'].lower() == resolved_state.lower()
                    and icar['district'].lower() == resolved_district.lower()):
                return icar

        # Pass 2: fuzzy match within the same state
        state_lower = resolved_state.lower()
        same_state = [d for d in all_icar if d['state'].lower() == state_lower]
        if same_state:
            candidates = [d['district'].lower() for d in same_state]
            matches = get_close_matches(resolved_district.lower(), candidates, n=1, cutoff=0.85)
            if matches:
                for icar in same_state:
                    if icar['district'].lower() == matches[0]:
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
