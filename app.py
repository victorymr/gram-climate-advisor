import streamlit as st
import json
import pandas as pd
from datetime import datetime
import sys
import os

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from rules import ScenarioClassifier
from advisory import AdvisoryGenerator
from utils import load_district_data, load_icar_data, get_district_list

st.set_page_config(
    page_title="Gram Climate Advisor",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 Rural Weather & Climate Risk Advisory")
st.markdown("Forecast-informed guidance for heat, monsoon delay, dry spells, and excess rainfall.")

# Sidebar inputs
st.sidebar.header("Location & User Information")

# Load district data
@st.cache_data
def load_data():
    districts = get_district_list()
    return districts

districts = load_data()

# State selection
states = sorted(list(set(d['state'] for d in districts)))
selected_state = st.sidebar.selectbox("Select State", states)

# District selection (filtered by state)
state_districts = [d for d in districts if d['state'] == selected_state]
district_names = sorted([d['district'] for d in state_districts])
selected_district = st.sidebar.selectbox("Select District", district_names)

# User type
user_types = [
    "Farmer",
    "Livestock owner", 
    "Outdoor worker",
    "Village official",
    "NGO / extension worker",
    "Health worker"
]
selected_user_type = st.sidebar.selectbox("User Type", user_types)

# Crop information
crop_types = [
    "Rice", "Maize", "Wheat", "Pulses", "Oilseeds", "Cotton", 
    "Sugarcane", "Vegetables", "Other"
]
selected_crop = st.sidebar.selectbox("Crop Type (Optional)", ["Not specified"] + crop_types)

# Irrigation status
irrigation_status = [
    "Rainfed",
    "Partial irrigation", 
    "Assured irrigation",
    "Unknown"
]
selected_irrigation = st.sidebar.selectbox("Irrigation Status", irrigation_status)

# Crop stage
crop_stages = [
    "Not sown",
    "Recently sown", 
    "Vegetative",
    "Flowering / reproductive",
    "Harvesting",
    "Unknown"
]
selected_crop_stage = st.sidebar.selectbox("Crop Stage (Optional)", ["Not specified"] + crop_stages)

# Generate advisory button
if st.sidebar.button("🌱 Get Advisory", type="primary"):
    # Load forecast and adaptation data
    forecast_data = load_district_data(selected_state, selected_district)
    icar_data = load_icar_data(selected_state, selected_district)
    
    # Create user context
    user_context = {
        "user_type": selected_user_type.lower().replace(" ", "_"),
        "crop": selected_crop.lower() if selected_crop != "Not specified" else None,
        "irrigation_status": selected_irrigation.lower().replace(" ", "_"),
        "crop_stage": selected_crop_stage.lower().replace(" / ", "_").replace(" ", "_") if selected_crop_stage != "Not specified" else None
    }
    
    # Classify scenarios
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(forecast_data, user_context)
    
    # Generate advisory
    advisor = AdvisoryGenerator()
    advisory = advisor.generate_advisory(
        selected_state, 
        selected_district, 
        forecast_data, 
        icar_data, 
        scenarios, 
        user_context
    )
    
    # Display advisory
    st.header("📍 Location & Risk Summary")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("District", f"{selected_district}, {selected_state}")
    with col2:
        risk_color = {
            "Low": "🟢",
            "Watch": "🟡", 
            "Alert": "🟠",
            "Severe": "🔴"
        }
        st.metric("Overall Risk", f"{risk_color.get(advisory['overall_risk'], '')} {advisory['overall_risk']}")
    with col3:
        st.metric("Confidence", advisory['scenarios'][0]['confidence'] if advisory['scenarios'] else "Low")
    
    # Main concerns
    if advisory['main_concerns']:
        st.subheader("⚠️ Main Concerns")
        for concern in advisory['main_concerns']:
            st.write(f"• {concern}")
    
    # Forecast summary
    st.subheader("🌤️ Forecast Summary")
    st.write(advisory['forecast_summary'])
    
    # Extended 4-week outlook
    if advisory.get('extended_outlook'):
        outlook = advisory['extended_outlook']
        st.subheader("📅 4-Week Extended Outlook")
        st.write(outlook['narrative'])
        
        # Week-by-week table
        outlook_rows = []
        for wk in outlook['weeks']:
            row = {
                "Week": f"Week {wk['week']}",
                "Rainfall": f"{wk['anomaly_mm_day']:+.0f} mm/day ({wk['label']})",
            }
            if 'tmax_anomaly_degC' in wk:
                row["Temperature"] = f"{wk['tmax_anomaly_degC']:+.0f}°C"
            else:
                row["Temperature"] = "—"
            outlook_rows.append(row)
        st.table(pd.DataFrame(outlook_rows))
    
    # Scenario details
    if advisory['scenarios']:
        st.subheader("🎯 Risk Scenarios")
        for scenario in advisory['scenarios']:
            risk_icon = {"Severe": "🔴", "Alert": "🟠", "Watch": "🟡"}.get(scenario['risk_level'], "⚪")
            st.markdown(
                f"**{risk_icon} {scenario['display_name']}** — "
                f"{scenario['risk_level']} risk (confidence: {scenario['confidence']})"
            )
            st.caption(" · ".join(scenario['reasons']))
    
    # Recommended actions
    st.subheader("📋 Recommended Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("**🔴 Do Now**")
        for action in advisory['actions_do_now']:
            st.write(f"• {action}")
    
    with col2:
        st.write("**🟡 Prepare (Weeks 2-4)**")
        for action in advisory['actions_prepare']:
            st.write(f"• {action}")
    
    with col3:
        st.write("**⛔ Avoid**")
        for action in advisory['actions_avoid']:
            st.write(f"• {action}")
    
    # General guidance (evergreen advice)
    if advisory.get('general_guidance'):
        st.markdown("---")
        st.markdown("**ℹ️ General Guidance (always applicable)**")
        st.write(" · ".join(advisory['general_guidance']))
    
    # Source forecast data
    st.subheader("📡 Source Forecast Data")
    
    # Week-by-week table
    forecast_rows = []
    for wk in range(1, 5):
        rain = forecast_data.get(f"week{wk}_rainfall_anomaly_mm_day")
        tmax = forecast_data.get(f"week{wk}_tmax_anomaly_degC")
        forecast_rows.append({
            "Week": f"Week {wk}",
            "Rainfall Anomaly (mm/day)": f"{rain:+.1f}" if rain is not None else "—",
            "Tmax Anomaly (°C)": f"{tmax:+.1f}" if tmax is not None else "—",
        })
    st.table(pd.DataFrame(forecast_rows))
    
    # Observed context
    obs_col1, obs_col2, obs_col3 = st.columns(3)
    with obs_col1:
        st.markdown(f"**Monsoon onset:** {forecast_data.get('monsoon_onset_status', '—')}")
        st.markdown(f"**Seasonal context:** {forecast_data.get('seasonal_monsoon_context', '—')}")
    with obs_col2:
        st.markdown(f"**Rainfall since Jun 1:** {forecast_data.get('rainfall_since_june_1_pct_departure', '—')}%")
        st.markdown(f"**Last 14 days:** {forecast_data.get('rainfall_last_14_days_pct_departure', '—')}%")
    with obs_col3:
        hw = "⚠️ Yes" if forecast_data.get("heat_wave_warning") else "No"
        hr = "⚠️ Yes" if forecast_data.get("heavy_rain_warning") else "No"
        st.markdown(f"**Heat wave warning:** {hw}")
        st.markdown(f"**Heavy rain warning:** {hr}")
    
    if forecast_data.get("imd_source_notes"):
        st.caption(f"Source note: {forecast_data['imd_source_notes']}")
    
    # Source notes
    st.subheader("📚 Source Notes")
    st.info(f"""
    **Forecast Source:** {advisory['source_notes']['forecast_source']}
    
    **Agriculture Source:** {advisory['source_notes']['agriculture_source']}
    
    **Health Source:** {advisory['source_notes']['health_source']}
    
    **Last Updated:** {advisory['source_notes']['last_updated']}
    """)
    
    # Disclaimer
    st.subheader("⚖️ Disclaimer")
    st.warning(advisory['disclaimer'])

else:
    st.info("👈 Select your location and user information, then click 'Get Advisory' to receive climate risk guidance.")

# Footer
st.markdown("---")
st.markdown("*This advisory system provides planning support based on official forecast data and agricultural contingency plans. Always follow local government instructions and seek professional advice for critical decisions.*")
