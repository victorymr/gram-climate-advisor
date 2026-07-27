import streamlit as st
import json
import pandas as pd
from datetime import datetime
from html import escape
import sys
import os

# Anchor to the app's own directory so every relative data path (here and in
# src/utils.py) resolves no matter where `streamlit run app.py` is launched from.
# Without this, launching from another directory makes the data files unreachable
# and the app silently falls back to the 10 hard-coded pilot districts.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_APP_DIR)

# Add src directory to path
sys.path.append(os.path.join(_APP_DIR, 'src'))

from rules import ScenarioClassifier
from advisory import AdvisoryGenerator
from utils import load_district_data, load_icar_data, get_district_list

try:
    import folium
    from streamlit_folium import st_folium
    _HAS_MAP = True
except Exception:
    _HAS_MAP = False


@st.cache_data
def load_district_geojson():
    """Simplified district polygons for the clickable map (built by build_district_list.py)."""
    p = os.path.join(_APP_DIR, "data", "districts.geojson")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


@st.cache_data
def _district_points():
    """(state, district, lat, lon) for map-click nearest-district lookup."""
    import csv as _csv
    with open(os.path.join(_APP_DIR, "data", "district_coordinates.csv"), encoding="utf-8") as fh:
        return [(r["state"], r["district"], float(r["latitude"]), float(r["longitude"]))
                for r in _csv.DictReader(fh)]


def nearest_district(lat, lng):
    s, d, _, _ = min(_district_points(), key=lambda p: (p[2] - lat) ** 2 + (p[3] - lng) ** 2)
    return s, d

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


# --- probabilistic outlook helpers -----------------------------------------
def _round10(p):
    """Round a probability (0-1) to the nearest 10%."""
    return int(round((p or 0.0) * 10)) * 10


def _likelihood_word(p):
    pct = (p or 0.0) * 100
    if pct < 10:
        return "Very unlikely"
    if pct < 30:
        return "Unlikely"
    if pct < 50:
        return "Possible"
    if pct < 70:
        return "Likely"
    if pct < 90:
        return "Very likely"
    return "Almost certain"


def _odds(p):
    return "—" if p is None else f"{_likelihood_word(p)} · {_round10(p)}%"


def _rain_lean(w):
    """Dominant of wetter/near/drier for a week's probability dict."""
    opts = {k: v for k, v in {
        "Wetter than normal": w.get("p_wetter"),
        "Near normal": w.get("p_near"),
        "Drier than normal": w.get("p_drier"),
    }.items() if v is not None}
    if not opts:
        return "—"
    lean, p = max(opts.items(), key=lambda kv: kv[1])
    return f"{lean} · {_round10(p)}%"


def _rain_category(v):
    """Plain-language rainfall category from a weekly anomaly (mm/day)."""
    if v is None:
        return "—"
    if v >= 7:
        return "Much wetter than normal"
    if v >= 3:
        return "Wetter than normal"
    if v >= 1:
        return "Slightly wetter"
    if v > -1:
        return "Near normal"
    if v > -3:
        return "Slightly drier"
    if v > -7:
        return "Drier than normal"
    return "Much drier than normal"


def _temp_category(v):
    """Plain-language temperature category from a weekly anomaly (°C)."""
    if v is None:
        return "—"
    if v >= 4:
        return "Very warm"
    if v >= 2:
        return "Warm"
    if v >= 1:
        return "Slightly warm"
    if v > -1:
        return "Near normal"
    if v > -2:
        return "Slightly cool"
    if v > -4:
        return "Cool"
    return "Very cool"


def _red_scale(frac):
    """Map 0..1 to a white -> dark-red background CSS, with readable text in both themes.
    Text is pinned (dark maroon on light red, white on deep red) so it doesn't depend on
    the viewer's light/dark theme."""
    frac = max(0.0, min(1.0, frac))
    r = int(round(255 + frac * (139 - 255)))
    g = int(round(255 + frac * (0 - 255)))
    b = int(round(255 + frac * (0 - 255)))
    txt = "#ffffff" if frac >= 0.5 else "#5a1a1a"
    return f"background-color:rgb({r},{g},{b}); color:{txt};"


def _temp_red(v):
    """Warmer weeks get deeper red (full at +6 °C); near-normal/cool stay uncolored."""
    if v is None or v < 1:
        return ""
    return _red_scale(v / 6.0)


def _precip_red(v):
    """Drier weeks get deeper red (full at −10 mm/day); near-normal/wetter stay uncolored."""
    if v is None or v > -1:
        return ""
    return _red_scale(-v / 10.0)


# --- nationwide forecast map (Source Data overview) ------------------------
def _mnorm(s):
    """Match geojson polygons to forecast records regardless of spacing/case."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


@st.cache_data
def _forecast_index():
    """(norm_state, norm_district) -> full forecast record, for the nationwide map."""
    p = os.path.join(_APP_DIR, "data", "district_forecasts.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        recs = json.load(fh)
    return {(_mnorm(r.get("state")), _mnorm(r.get("district"))): r for r in recs}


# map variable -> where to read the value + diverging colour ramp (white ≈ near-normal,
# saturating to a hue at |value| == span). RGB endpoints. Weekly variables read a per-source
# value from forecast_variants (wkey), falling back to the top-level MME field (topfield).
MAP_VARIABLES = {
    "Rainfall": dict(
        weekly=True, wkey="rainfall_mm_day", topfield="week{w}_rainfall_anomaly_mm_day",
        unit="mm/day", span=8.0, neg=(166, 97, 26), pos=(33, 102, 172),   # dry=brown, wet=blue
        neg_lab="Drier", pos_lab="Wetter", fmt="{:+.1f}"),
    "Temperature": dict(
        weekly=True, wkey="tmax_degC", topfield="week{w}_tmax_anomaly_degC",
        unit="°C", span=5.0, neg=(33, 102, 172), pos=(178, 24, 43),       # cool=blue, hot=red
        neg_lab="Cooler", pos_lab="Hotter", fmt="{:+.1f}"),
    "Season rainfall departure": dict(
        weekly=False, field="rainfall_since_june_1_pct_departure",
        unit="%", span=60.0, neg=(166, 97, 26), pos=(33, 102, 172),       # deficit=brown, surplus=blue
        neg_lab="Deficit", pos_lab="Surplus", fmt="{:+.0f}"),
}

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _variant_week_value(rec, source_key, wkey, week, topfield):
    """A weekly value for one district: the chosen source's forecast_variant if present,
    else the top-level MME field (also the fallback when data predates variants)."""
    if source_key and rec:
        var = next((v for v in rec.get("forecast_variants", []) if v.get("key") == source_key), None)
        if var:
            w = next((x for x in var.get("weeks", []) if x.get("week") == week), None)
            if w is not None:
                return w.get(wkey)
    return rec.get(topfield.format(w=week)) if rec else None


def _season_range(rec):
    """'Jun 1 – Jul 8, 2026' from a record's observed_source ('... asof YYYY-MM-DD')."""
    src = (rec or {}).get("observed_source", "") or ""
    if "asof" not in src:
        return None
    try:
        y, mo, d = src.split("asof")[-1].strip().split()[0].split("-")
        return f"Jun 1 – {_MONTHS[int(mo)]} {int(d)}, {y}"
    except Exception:
        return None


def _parse_init(s):
    """date from an init string, '2026-07-11' or '20260711' (None if unparseable)."""
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _week_dates(init, week):
    """(start, end) valid dates for forecast week W (week 1 = init+1 … init+7)."""
    from datetime import timedelta
    d = _parse_init(init)
    if not d:
        return None
    return d + timedelta(days=7 * (week - 1) + 1), d + timedelta(days=7 * week)


def _fmt_range(start, end):
    """'Jul 12–18' (same month) or 'Jul 26 – Aug 1' (spanning months)."""
    if start.month == end.month:
        return f"{_MONTHS[start.month]} {start.day}–{end.day}"
    return f"{_MONTHS[start.month]} {start.day} – {_MONTHS[end.month]} {end.day}"


def _week_label(init, week, sep=" · "):
    """'Week 1 · Jul 12–18' (falls back to 'Week N' if init is unparseable)."""
    r = _week_dates(init, week)
    return f"Week {week}{sep}{_fmt_range(*r)}" if r else f"Week {week}"


def _map_color(v, cfg):
    """Diverging hex colour for a value under a variable's ramp (grey if missing)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "#e6e6e6"
    t = max(-1.0, min(1.0, float(v) / cfg["span"]))
    end = cfg["pos"] if t >= 0 else cfg["neg"]
    a = abs(t)
    r = round(255 + a * (end[0] - 255))
    g = round(255 + a * (end[1] - 255))
    b = round(255 + a * (end[2] - 255))
    return f"#{r:02x}{g:02x}{b:02x}"


@st.cache_data
def _enriched_geojson(variable_key, week, source_key):
    """District polygons deep-copied with the chosen variable/week/source value + a label.
    source_key selects a forecast_variant for weekly variables; it's ignored for the
    (observed, single-source) season departure."""
    import copy
    base = load_district_geojson()
    if not base:
        return None
    cfg = MAP_VARIABLES[variable_key]
    idx = _forecast_index()
    geo = copy.deepcopy(base)
    for feat in geo.get("features", []):
        pr = feat.setdefault("properties", {})
        rec = idx.get((_mnorm(pr.get("state")), _mnorm(pr.get("district"))))
        if cfg.get("weekly"):
            v = _variant_week_value(rec, source_key, cfg["wkey"], week, cfg["topfield"])
        else:
            v = rec.get(cfg["field"]) if rec else None
        pr["_val"] = v
        pr["_label"] = "n/a" if v is None else f"{cfg['fmt'].format(v)} {cfg['unit']}"
    return geo


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
states = sorted(list(set(d['state'] for d in districts)))

# Visible load indicator: the full dataset is 666 districts. If only the 10-district
# fallback loaded, the data files weren't found — surface that instead of failing silently.
if len(districts) <= 10:
    st.sidebar.warning(
        f"⚠️ Only {len(districts)} districts loaded — data files not found, using the "
        f"built-in fallback. Fully stop Streamlit (Ctrl-C) and rerun `streamlit run app.py` "
        f"from the project root."
    )
else:
    st.sidebar.caption(f"✅ {len(districts)} districts · {len(states)} states/UTs loaded")

# Choose how to pick the district: dropdowns, or click a map (rendered in the main panel).
input_mode = st.sidebar.radio(
    "Select by", ["Dropdowns", "Map"], horizontal=True, disabled=not _HAS_MAP,
    help=None if _HAS_MAP else "Install streamlit-folium to enable the map.",
)

if input_mode == "Map" and _HAS_MAP:
    sel = st.session_state.get("map_sel")
    if sel:
        selected_state, selected_district = sel
        st.sidebar.success(f"📍 {selected_district}, {selected_state}")
    else:
        selected_state = selected_district = None
        st.sidebar.caption("👉 Click a district on the map in the main panel.")
else:
    selected_state = st.sidebar.selectbox("Select State", states)
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
show_actions = st.sidebar.checkbox(
    "Show adaptation actions", value=True,
    help="Uncheck for a forecast-only view — hides the Do Now / Prepare / Avoid cards "
         "and general guidance (which are still generic for most districts).",
)

# Generate advisory button. We gate rendering on session_state (not the button's
# transient True) so widgets *inside* the results — e.g. the Source Data source
# switcher — don't clear the advisory when they trigger a rerun. The body recomputes
# from the current sidebar selections on every run, so it always stays in sync.
if st.sidebar.button("🌱 Get Advisory", type="primary", use_container_width=True):
    st.session_state["advisory_shown"] = True

# --- Clickable district map (Map mode): click a district -> select + show advisory ---
if input_mode == "Map" and _HAS_MAP:
    st.markdown("<div class='sec-title'>🗺️ Click a district to select it</div>", unsafe_allow_html=True)
    geo = load_district_geojson()
    if not geo:
        st.warning("Map data not found — run `python scripts/build_district_list.py`.")
    else:
        fmap = folium.Map(location=[22.5, 80.5], zoom_start=4, tiles="cartodbpositron", control_scale=True)
        folium.GeoJson(
            geo, name="districts",
            style_function=lambda f: {"fillColor": "#74a9cf", "color": "#5a5a5a",
                                      "weight": 0.4, "fillOpacity": 0.30},
            highlight_function=lambda f: {"fillColor": "#fd8d3c", "fillOpacity": 0.75, "weight": 1.2},
            tooltip=folium.GeoJsonTooltip(fields=["district", "state"],
                                          aliases=["District", "State"], sticky=True),
        ).add_to(fmap)
        _ret = st_folium(fmap, height=440, use_container_width=True,
                         returned_objects=["last_clicked"], key="district_map")
        if _ret and _ret.get("last_clicked"):
            _s, _d = nearest_district(_ret["last_clicked"]["lat"], _ret["last_clicked"]["lng"])
            if st.session_state.get("map_sel") != (_s, _d):
                st.session_state["map_sel"] = (_s, _d)
                st.session_state["advisory_shown"] = True
                st.rerun()

if st.session_state.get("advisory_shown") and selected_state and selected_district:
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
    if show_actions:
        st.markdown("<div class='sec-title'>📋 Recommended Actions</div>", unsafe_allow_html=True)
        # date span for the "prepare" window (start of week 2 → end of week 4)
        _w2 = _week_dates(forecast_data.get("forecast_date"), 2)
        _w4 = _week_dates(forecast_data.get("forecast_date"), 4)
        _prep = f"Prepare (Weeks 2-4 · {_fmt_range(_w2[0], _w4[1])})" if _w2 and _w4 else "Prepare (Weeks 2-4)"
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            render_action_card("Do Now", "�", advisory['actions_do_now'],
                               "card-do", "No immediate actions flagged.")
        with ac2:
            render_action_card(_prep, "🟡", advisory['actions_prepare'],
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
            _init = forecast_data.get("forecast_date")
            df_out = pd.DataFrame([
                {
                    "Week": _week_label(_init, wk['week']),
                    "Rainfall": _rain_category(wk.get('anomaly_mm_day')),
                    "Temperature": _temp_category(wk.get('tmax_anomaly_degC')),
                }
                for wk in weeks
            ]).set_index("Week")

            # Heat-map the cells: hotter and drier weeks shade increasingly dark red.
            cell_styles = pd.DataFrame("", index=df_out.index, columns=df_out.columns)
            for i, wk in enumerate(weeks):
                idx = df_out.index[i]
                cell_styles.loc[idx, "Rainfall"] = _precip_red(wk.get('anomaly_mm_day'))
                cell_styles.loc[idx, "Temperature"] = _temp_red(wk.get('tmax_anomaly_degC'))
            st.dataframe(df_out.style.apply(lambda _: cell_styles, axis=None),
                         use_container_width=True)

            st.info(
                "ℹ️ These are broad categories relative to the seasonal normal. "
                "For the **odds** of specific thresholds (heavy rain, dry spell, hot week) "
                "and exact model values, see the **📡 Source Data** tab."
            )
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
        # Source switcher: official IMD guidance, the downloaded multi-model mean,
        # or an individual model. Falls back to the active top-level fields if the
        # data predates the model import (no forecast_variants present).
        # Only offer sources that actually carry numeric weekly values — this hides the
        # hand-curated "Official IMD guidance" variant for the districts where it's empty
        # (IMD publishes no per-district numeric extended forecast; kept for the pilots).
        variants = [v for v in (forecast_data.get("forecast_variants") or [])
                    if any((w.get("rainfall_mm_day") is not None or
                            w.get("tmax_degC") is not None) for w in v.get("weeks", []))]
        selected_variant = None
        if variants:
            labels = [v.get("label", v.get("key", "?")) for v in variants]
            st.caption(
                "Compare the forecast inputs behind this advisory. The recommendations "
                "above use the **multi-model mean**."
            )
            choice = st.radio("Forecast source", labels, horizontal=True,
                              label_visibility="collapsed")
            selected_variant = variants[labels.index(choice)] if choice in labels else variants[0]
            weeks = selected_variant.get("weeks", [])
        else:
            weeks = [{"week": wk,
                      "rainfall_mm_day": forecast_data.get(f"week{wk}_rainfall_anomaly_mm_day"),
                      "tmax_degC": forecast_data.get(f"week{wk}_tmax_anomaly_degC")}
                     for wk in range(1, 5)]

        _init = forecast_data.get("forecast_date")
        df_src = pd.DataFrame([
            {"Week": _week_label(_init, w['week']),
             "Rainfall (mm/day)": w.get("rainfall_mm_day"),
             "Tmax (°C)": w.get("tmax_degC")}
            for w in weeks
        ]).set_index("Week")
        src_styler = (
            df_src.style
            .map(_rain_cell_color, subset=["Rainfall (mm/day)"])
            .map(_temp_cell_color, subset=["Tmax (°C)"])
            .format({"Rainfall (mm/day)": "{:+.1f}", "Tmax (°C)": "{:+.1f}"}, na_rep="—")
        )
        st.dataframe(src_styler, use_container_width=True)
        if selected_variant and selected_variant.get("source"):
            st.caption(f"**{selected_variant['label']}** — {selected_variant['source']}")

        # Weekly threshold odds (ensemble probabilities)
        wprob = forecast_data.get("weekly_probabilities")
        if wprob and wprob.get("weeks"):
            pweeks = wprob["weeks"]
            _pinit = wprob.get("init") or forecast_data.get("forecast_date")
            st.markdown("<div class='sec-title'>🎲 Weekly threshold odds</div>", unsafe_allow_html=True)
            df_p = pd.DataFrame([
                {
                    "Week": _week_label(_pinit, w['week']),
                    "Rainfall lean": _rain_lean(w),
                    "Heavy rain": _odds(w.get("p_heavy")),
                    "Dry spell": _odds(w.get("p_dryspell")),
                    "Hot week": _odds(w.get("p_hot")),
                }
                for w in pweeks
            ]).set_index("Week")
            st.dataframe(df_p, use_container_width=True)

            split = pd.DataFrame([
                {
                    "Week": _week_label(_pinit, w['week']),
                    "Wetter": round((w.get('p_wetter') or 0) * 100),
                    "Near": round((w.get('p_near') or 0) * 100),
                    "Drier": round((w.get('p_drier') or 0) * 100),
                }
                for w in pweeks
            ]).set_index("Week")
            st.caption("Rainfall category odds (%)")
            try:
                st.bar_chart(split, color=["#2980b9", "#b0b0b0", "#c0904f"], stack=True)
            except TypeError:
                st.bar_chart(split)

            n = wprob.get("n_members", "?")
            src = wprob.get("source", "ensemble")
            init = wprob.get("init") or forecast_data.get("forecast_date", "")
            st.caption(f"Odds from the {src} ({n} members), init {init}; rounded to the nearest 10%.")

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

        if forecast_data.get("forecast_source"):
            st.caption(f"Forecast source: {forecast_data['forecast_source']}")
        if forecast_data.get("imd_source_notes"):
            st.caption(f"Source note: {forecast_data['imd_source_notes']}")

        # --- Nationwide overview map: the same national picture for every district,
        # with the current district outlined so it's placed in context. ---
        geo_base = load_district_geojson() if _HAS_MAP else None
        if _HAS_MAP and geo_base:
            st.divider()
            st.markdown("<div class='sec-title'>🗺️ Nationwide outlook</div>", unsafe_allow_html=True)
            st.caption("A country-wide view of the same forecast, with your district outlined.")
            variable_key = st.radio("Variable", list(MAP_VARIABLES.keys()),
                                    horizontal=True, label_visibility="collapsed",
                                    key="natmap_var")
            cfg = MAP_VARIABLES[variable_key]
            _minit = forecast_data.get("forecast_date")

            # Data-source options: the model forecast_variants that carry numeric weekly
            # values (MME, CFSv2, EC46, GEFS); the qualitative IMD guidance can't be mapped.
            _src_variants = [v for v in (forecast_data.get("forecast_variants") or [])
                             if any((w.get("rainfall_mm_day") is not None or
                                     w.get("tmax_degC") is not None) for w in v.get("weeks", []))]
            _src_labels = [v["label"] for v in _src_variants]
            _key_by_label = {v["label"]: v["key"] for v in _src_variants}

            mcol1, mcol2 = st.columns(2)
            with mcol1:
                if _src_labels:
                    source_label = st.selectbox("Data source", _src_labels,
                                                disabled=not cfg.get("weekly"),
                                                key="natmap_src")
                    source_key = _key_by_label.get(source_label)
                else:
                    source_label, source_key = None, None
            with mcol2:
                week = st.selectbox("Week", [1, 2, 3, 4],
                                    format_func=lambda w: _week_label(_minit, w, sep=" — "),
                                    disabled=not cfg.get("weekly"),
                                    key="natmap_week")
            geo = _enriched_geojson(variable_key, week, source_key)
            sel = (_mnorm(selected_state), _mnorm(selected_district))

            def _nat_style(feat, _sel=sel, _cfg=cfg):
                pr = feat["properties"]
                here = (_mnorm(pr.get("state")), _mnorm(pr.get("district"))) == _sel
                return {"fillColor": _map_color(pr.get("_val"), _cfg),
                        "color": "#111111" if here else "#8a8a8a",
                        "weight": 2.8 if here else 0.3,
                        "fillOpacity": 0.82}

            fmap = folium.Map(location=[22.4, 80.5], zoom_start=4,
                              tiles="cartodbpositron", control_scale=False)
            folium.GeoJson(
                geo, name="forecast", style_function=_nat_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=["district", "state", "_label"],
                    aliases=["District", "State", "Outlook:"], sticky=True),
            ).add_to(fmap)
            st_folium(fmap, height=460, use_container_width=True,
                      returned_objects=[], key="national_forecast_map")

            if cfg.get("weekly"):
                _wr = _week_dates(_minit, week)
                _dates = f" ({_fmt_range(*_wr)})" if _wr else ""
                _src = f" · {source_label}" if source_label else ""
                scope = f"{variable_key} — Week {week}{_dates} vs seasonal normal{_src}"
            else:
                rng = _season_range(forecast_data)
                scope = "Season rainfall departure (observed, IMD)" + (f" · {rng}" if rng else "")
            neg, pos = f"rgb{cfg['neg']}", f"rgb{cfg['pos']}"
            st.markdown(
                f"<div style='font-size:0.92rem;font-weight:600;margin-bottom:5px;'>{scope}</div>"
                f"<div style='display:flex;align-items:center;gap:10px;font-size:0.85rem;'>"
                f"<span>{cfg['neg_lab']}</span>"
                f"<span style='flex:1;height:12px;border-radius:3px;border:1px solid #bbb;"
                f"background:linear-gradient(to right,{neg},#ffffff,{pos});'></span>"
                f"<span>{cfg['pos_lab']}</span></div>"
                f"<div style='font-size:0.75rem;color:#888;margin-top:2px;'>"
                f"White ≈ near normal · full colour at ±{cfg['span']:g} {cfg['unit']} · "
                f"your district is outlined in black. Hover any district for its value.</div>",
                unsafe_allow_html=True)

    # --- Sources & disclaimer tab ---
    with tab_sources:
        st.info(f"""
        **Forecast Source:** {advisory['source_notes']['forecast_source']}
        
        **Agriculture Source:** {advisory['source_notes']['agriculture_source']}
        
        **Health Source:** {advisory['source_notes']['health_source']}
        
        **Last Updated:** {advisory['source_notes']['last_updated']}
        """)
        st.warning(advisory['disclaimer'])

elif st.session_state.get("advisory_shown"):
    st.info("👆 Click a district on the map (or switch to Dropdowns) to see its advisory.")
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
