import streamlit as st
import json
import pandas as pd
from datetime import datetime
from html import escape
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

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1200px;}

    /* App header */
    .app-header h1 {margin-bottom: 0.2rem;}
    .app-header p {color: #5f6b7a; font-size: 1rem; margin-top: 0;}

    /* Risk banner */
    .risk-banner {
        border-radius: 16px; padding: 1.4rem 1.6rem; color: #fff;
        margin: 0.5rem 0 1.2rem 0; box-shadow: 0 6px 18px rgba(0,0,0,0.14);
    }
    .risk-banner h2 {margin: 0; font-size: 1.7rem; color: #fff; font-weight: 700;}
    .risk-banner .sub {opacity: 0.95; font-size: 0.98rem; margin-top: 0.4rem; line-height: 1.4;}
    .risk-meta {display: flex; gap: 2.5rem; margin-top: 1rem; flex-wrap: wrap;}
    .risk-meta .item {font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.85;}
    .risk-meta .item b {display: block; font-size: 1.15rem; letter-spacing: 0; text-transform: none; opacity: 1; margin-top: 0.1rem;}

    /* Concern chips */
    .chip {
        display: inline-block; padding: 0.32rem 0.85rem; margin: 0.2rem 0.35rem 0.2rem 0;
        border-radius: 999px; font-size: 0.85rem; font-weight: 600;
        background: #fff3e0; color: #e65100; border: 1px solid #ffcc80;
    }

    /* Action cards */
    .action-card {
        border-radius: 14px; padding: 1.1rem 1.2rem; height: 100%;
        border: 1px solid #e0e0e0; background: #fafafa;
    }
    .action-card h4 {margin: 0 0 0.7rem 0; font-size: 1.05rem; display: flex; align-items: center; gap: 0.4rem;}
    .action-card ul {margin: 0; padding-left: 1.15rem;}
    .action-card li {margin-bottom: 0.45rem; font-size: 0.92rem; line-height: 1.4; color: #2c3e50;}
    .card-do    {background: #fdecea; border-color: #f5b7b1;}
    .card-do h4 {color: #c0392b;}
    .card-prep  {background: #fef9e7; border-color: #f7dc6f;}
    .card-prep h4 {color: #b9770e;}
    .card-avoid {background: #f4f6f7; border-color: #d5dbdb;}
    .card-avoid h4 {color: #566573;}

    /* Section title (on page background — inherit theme text color) */
    .sec-title {font-size: 1.25rem; font-weight: 700; margin: 1.4rem 0 0.5rem 0;}

    /* Guidance box */
    .guidance-box {
        background: #eef5fb; border: 1px solid #c9dcef; border-radius: 12px;
        padding: 0.9rem 1.1rem; font-size: 0.92rem; color: #34495e; line-height: 1.5;
    }

    /* Landing steps */
    .step-card {
        border: 1px solid #e0e0e0; border-radius: 12px; padding: 1.1rem; height: 100%;
        background: #fff;
    }
    .step-card .num {
        display: inline-flex; align-items: center; justify-content: center;
        width: 2rem; height: 2rem; border-radius: 50%; background: #27ae60; color: #fff;
        font-weight: 700; margin-bottom: 0.6rem;
    }
    .step-card h4 {margin: 0.2rem 0 0.4rem 0; color: #2c3e50;}
    .step-card p {color: #5f6b7a; font-size: 0.9rem; margin: 0;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Theme + render helpers (presentation only)
# ---------------------------------------------------------------------------
RISK_THEME = {
    "Severe": {"bg": "linear-gradient(135deg,#922b21,#e74c3c)", "icon": "🔴"},
    "Alert":  {"bg": "linear-gradient(135deg,#a04000,#e67e22)", "icon": "🟠"},
    "Watch":  {"bg": "linear-gradient(135deg,#9a7d0a,#f1c40f)", "icon": "🟡"},
    "Low":    {"bg": "linear-gradient(135deg,#196f3d,#27ae60)", "icon": "🟢"},
}


def render_risk_banner(district, state, risk, confidence, n_concerns, summary):
    theme = RISK_THEME.get(risk, RISK_THEME["Low"])
    st.markdown(f"""
    <div class="risk-banner" style="background:{theme['bg']};">
        <h2>{theme['icon']} {escape(risk)} Risk &nbsp;·&nbsp; {escape(district)}, {escape(state)}</h2>
        <div class="sub">{escape(summary)}</div>
        <div class="risk-meta">
            <div class="item">Overall Risk<b>{escape(risk)}</b></div>
            <div class="item">Confidence<b>{escape(confidence)}</b></div>
            <div class="item">Active Concerns<b>{n_concerns}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_action_card(title, icon, items, css_class, empty_msg):
    if items:
        lis = "".join(f"<li>{escape(str(i))}</li>" for i in items)
    else:
        lis = f"<li style='opacity:0.55;list-style:none;margin-left:-1rem;'>{escape(empty_msg)}</li>"
    st.markdown(
        f"<div class='action-card {css_class}'><h4>{icon} {escape(title)}</h4><ul>{lis}</ul></div>",
        unsafe_allow_html=True,
    )


def _rain_cell_color(v):
    if v is None or pd.isna(v):
        return ""
    if v <= -3:
        return "background-color:#f5b7b1; color:#7b241c;"
    if v <= -1:
        return "background-color:#fad7d4;"
    if v >= 7:
        return "background-color:#aed6f1; color:#1a5276;"
    if v >= 3:
        return "background-color:#d4e6f1;"
    return ""


def _temp_cell_color(v):
    if v is None or pd.isna(v):
        return ""
    if v >= 4:
        return "background-color:#f5b7b1; color:#7b241c;"
    if v >= 1.5:
        return "background-color:#fad7d4;"
    if v <= -1.5:
        return "background-color:#d4e6f1; color:#1a5276;"
    return ""


# App header
st.markdown("""
<div class="app-header">
    <h1>🌾 Rural Weather & Climate Risk Advisory</h1>
    <p>Forecast-informed guidance for heat, monsoon delay, dry spells, and excess rainfall.</p>
</div>
""", unsafe_allow_html=True)

# Sidebar inputs
st.sidebar.markdown("### 📍 Location")

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

st.sidebar.markdown("### 👤 Your Context")

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

st.sidebar.markdown("&nbsp;")

# Generate advisory button
if st.sidebar.button("🌱 Get Advisory", type="primary", use_container_width=True):
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
    
    # ----- Hero risk banner -----
    confidence = advisory['scenarios'][0]['confidence'] if advisory['scenarios'] else "Low"
    render_risk_banner(
        selected_district, selected_state,
        advisory['overall_risk'], confidence,
        len(advisory['main_concerns']),
        advisory['forecast_summary'],
    )

    # ----- Concern chips -----
    if advisory['main_concerns']:
        chips = "".join(f"<span class='chip'>⚠️ {escape(str(c))}</span>" for c in advisory['main_concerns'])
        st.markdown(f"<div style='margin-bottom:0.6rem;'>{chips}</div>", unsafe_allow_html=True)

    # ----- Recommended actions (above the fold) -----
    st.markdown("<div class='sec-title'>📋 Recommended Actions</div>", unsafe_allow_html=True)
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        render_action_card("Do Now", "�", advisory['actions_do_now'],
                           "card-do", "No immediate actions flagged.")
    with ac2:
        render_action_card("Prepare (Weeks 2-4)", "🟡", advisory['actions_prepare'],
                           "card-prep", "No preparatory actions flagged.")
    with ac3:
        render_action_card("Avoid", "⛔", advisory['actions_avoid'],
                           "card-avoid", "No specific cautions flagged.")

    # ----- General guidance -----
    if advisory.get('general_guidance'):
        guidance = " · ".join(escape(str(g)) for g in advisory['general_guidance'])
        st.markdown(
            f"<div class='sec-title'>ℹ️ General Guidance</div>"
            f"<div class='guidance-box'>{guidance}</div>",
            unsafe_allow_html=True,
        )

    # ----- Detail tabs -----
    st.markdown("<div style='margin-top:1.4rem'></div>", unsafe_allow_html=True)
    tab_outlook, tab_scenarios, tab_data, tab_sources = st.tabs(
        ["📅 4-Week Outlook", "🎯 Risk Scenarios", "📡 Source Data", "📚 Sources & Disclaimer"]
    )

    # --- Outlook tab ---
    with tab_outlook:
        if advisory.get('extended_outlook'):
            outlook = advisory['extended_outlook']
            st.write(outlook['narrative'])

            weeks = outlook['weeks']
            df_out = pd.DataFrame([
                {
                    "Week": f"Week {wk['week']}",
                    "Rainfall (mm/day)": wk['anomaly_mm_day'],
                    "Outlook": wk['label'],
                    "Temp anomaly (°C)": wk.get('tmax_anomaly_degC'),
                }
                for wk in weeks
            ]).set_index("Week")

            styler = (
                df_out.style
                .map(_rain_cell_color, subset=["Rainfall (mm/day)"])
                .map(_temp_cell_color, subset=["Temp anomaly (°C)"])
                .format({"Rainfall (mm/day)": "{:+.1f}", "Temp anomaly (°C)": "{:+.1f}"}, na_rep="—")
            )
            st.dataframe(styler, use_container_width=True)

            ch1, ch2 = st.columns(2)
            with ch1:
                st.caption("Rainfall anomaly (mm/day)")
                st.bar_chart(df_out[["Rainfall (mm/day)"]], color="#2980b9")
            with ch2:
                st.caption("Temperature anomaly (°C)")
                temp_series = df_out[["Temp anomaly (°C)"]].dropna()
                if not temp_series.empty:
                    st.bar_chart(temp_series, color="#e74c3c")
                else:
                    st.info("No temperature anomaly data available.")
        else:
            st.info("No extended outlook available for this district.")

    # --- Scenarios tab ---
    with tab_scenarios:
        if advisory['scenarios']:
            for scenario in advisory['scenarios']:
                risk_icon = {"Severe": "🔴", "Alert": "🟠", "Watch": "🟡"}.get(scenario['risk_level'], "⚪")
                with st.container(border=True):
                    st.markdown(
                        f"**{risk_icon} {scenario['display_name']}** — "
                        f"{scenario['risk_level']} risk (confidence: {scenario['confidence']})"
                    )
                    st.caption(" · ".join(scenario['reasons']))
        else:
            st.success("✅ No risk scenarios triggered. Baseline planning guidance applies.")

    # --- Source data tab ---
    with tab_data:
        forecast_rows = []
        for wk in range(1, 5):
            forecast_rows.append({
                "Week": f"Week {wk}",
                "Rainfall (mm/day)": forecast_data.get(f"week{wk}_rainfall_anomaly_mm_day"),
                "Tmax (°C)": forecast_data.get(f"week{wk}_tmax_anomaly_degC"),
            })
        df_src = pd.DataFrame(forecast_rows).set_index("Week")
        src_styler = (
            df_src.style
            .map(_rain_cell_color, subset=["Rainfall (mm/day)"])
            .map(_temp_cell_color, subset=["Tmax (°C)"])
            .format({"Rainfall (mm/day)": "{:+.1f}", "Tmax (°C)": "{:+.1f}"}, na_rep="—")
        )
        st.dataframe(src_styler, use_container_width=True)

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

    # --- Sources & disclaimer tab ---
    with tab_sources:
        st.info(f"""
        **Forecast Source:** {advisory['source_notes']['forecast_source']}
        
        **Agriculture Source:** {advisory['source_notes']['agriculture_source']}
        
        **Health Source:** {advisory['source_notes']['health_source']}
        
        **Last Updated:** {advisory['source_notes']['last_updated']}
        """)
        st.warning(advisory['disclaimer'])

else:
    st.info("👈 Select your location and context in the sidebar, then click **Get Advisory**.")

    st.markdown("<div class='sec-title'>How it works</div>", unsafe_allow_html=True)
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("""
        <div class="step-card">
            <div class="num">1</div>
            <h4>Pick your location</h4>
            <p>Select your state and district to load the latest IMD-based forecast.</p>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        st.markdown("""
        <div class="step-card">
            <div class="num">2</div>
            <h4>Add your context</h4>
            <p>Tell us your role, crop, irrigation, and crop stage for tailored advice.</p>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        st.markdown("""
        <div class="step-card">
            <div class="num">3</div>
            <h4>Get an action plan</h4>
            <p>Receive risk-rated guidance: what to do now, prepare for, and avoid.</p>
        </div>
        """, unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown("*This advisory system provides planning support based on official forecast data and agricultural contingency plans. Always follow local government instructions and seek professional advice for critical decisions.*")
