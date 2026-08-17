"""Area coverage: validate the generated district_forecasts.json across ALL districts —
required fields, value ranges, probability sanity, variant structure, enum validity, and
alignment with the district master list."""
import csv
import json
import math
from pathlib import Path

from utils import load_icar_data

ROOT = Path(__file__).resolve().parent.parent
FC = json.load(open(ROOT / "data" / "district_forecasts.json", encoding="utf-8"))
META = [(r["state"], r["district"]) for r in
        csv.DictReader(open(ROOT / "data" / "district_coordinates.csv", encoding="utf-8"))]

REQUIRED = ["state", "district", "monsoon_onset_status", "seasonal_monsoon_context",
            "week1_rainfall_signal", "week2_rainfall_signal", "week3_4_rainfall_signal",
            "tmax_signal", "heat_wave_warning", "heavy_rain_warning",
            "rainfall_since_june_1_pct_departure"]
SIGNALS = {"below_normal", "near_normal", "above_normal"}
ONSET = {"not_started", "delayed", "normal", "active", "weak"}
CONTEXT = {"below_normal_risk", "normal", "above_normal"}


def _tag(f):
    return f"{f.get('district')}, {f.get('state')}"


def test_covers_all_districts():
    assert len(FC) > 600


def test_alignment_with_master_list():
    jk = {(f["state"], f["district"]) for f in FC}
    mk = set(META)
    assert jk == mk, f"json-only={list(jk - mk)[:5]}  list-only={list(mk - jk)[:5]}"


def test_required_fields_present():
    missing = [(_tag(f), k) for f in FC for k in REQUIRED if k not in f]
    assert not missing, missing[:10]


def test_enums_valid():
    bad = []
    for f in FC:
        if f["monsoon_onset_status"] not in ONSET:
            bad.append((_tag(f), "onset", f["monsoon_onset_status"]))
        if f["seasonal_monsoon_context"] not in CONTEXT:
            bad.append((_tag(f), "context", f["seasonal_monsoon_context"]))
        for s in ("week1_rainfall_signal", "week2_rainfall_signal", "week3_4_rainfall_signal", "tmax_signal"):
            if f.get(s) not in SIGNALS:
                bad.append((_tag(f), s, f.get(s)))
    assert not bad, bad[:10]


def test_weekly_anomalies_in_sane_range():
    bad = []
    for f in FC:
        for w in (1, 2, 3, 4):
            r = f.get(f"week{w}_rainfall_anomaly_mm_day")
            t = f.get(f"week{w}_tmax_anomaly_degC")
            if r is not None and not (-60 <= r <= 60):
                bad.append((_tag(f), f"wk{w}_rain", r))
            if t is not None and not (-25 <= t <= 25):
                bad.append((_tag(f), f"wk{w}_tmax", t))
    assert not bad, bad[:10]


def test_observed_departures_in_sane_range():
    bad = [(_tag(f), k, f.get(k)) for f in FC
           for k in ("rainfall_since_june_1_pct_departure", "rainfall_last_7_days_pct_departure",
                     "rainfall_last_14_days_pct_departure")
           if f.get(k) is not None and not (-100 <= f[k] <= 400)]
    assert not bad, bad[:10]


def test_weekly_probabilities_valid():
    bad = []
    for f in FC:
        wp = f.get("weekly_probabilities")
        if not wp:
            continue
        assert wp.get("n_members", 0) and wp["n_members"] > 0, _tag(f)
        for wk in wp["weeks"]:
            for k in ("p_wetter", "p_near", "p_drier", "p_heavy", "p_dryspell", "p_hot"):
                v = wk.get(k)
                if v is not None and not (0.0 <= v <= 1.001):
                    bad.append((_tag(f), f"wk{wk['week']}:{k}", v))
            terc = [wk.get(k) for k in ("p_wetter", "p_near", "p_drier")]
            if all(v is not None for v in terc) and not math.isclose(sum(terc), 1.0, abs_tol=0.02):
                bad.append((_tag(f), f"wk{wk['week']}:tercile_sum", round(sum(terc), 3)))
    assert not bad, bad[:10]


def test_forecast_variants_wellformed():
    bad = []
    for f in FC:
        variants = f.get("forecast_variants")
        if not variants:
            bad.append((_tag(f), "missing forecast_variants"))
            continue
        keys = {v.get("key") for v in variants}
        if not {"IMD", "MME"} <= keys:
            bad.append((_tag(f), f"keys={keys}"))
        for v in variants:
            if not isinstance(v.get("weeks"), list) or not v["weeks"]:
                bad.append((_tag(f), f"{v.get('key')}: bad weeks"))
    assert not bad, bad[:10]


def test_icar_resolves_across_zones():
    # every district resolves to an ICAR entry (extracted or the generic fallback)
    for st, di in [("Bihar", "Gaya"), ("Kerala", "Wayanad"), ("Rajasthan", "Jaipur"),
                   ("Assam", "Cachar"), ("Tamil Nadu", "Coimbatore"), ("Punjab", "Ludhiana")]:
        ic = load_icar_data(st, di)
        assert "scenarios" in ic and "delayed_monsoon" in ic["scenarios"], (st, di)


def test_icar_alias_spelling_variants():
    """Spelling variants in ICAR vs forecast data should resolve to real ICAR data."""
    from utils import get_default_icar_data
    cases = [
        ("Karnataka", "Mysuru", "Mysore"),
        ("Karnataka", "Ballari", "Bellary"),
        ("Maharashtra", "Nashik", "Nasik"),
        ("Bihar", "Begusarai", "Begusari"),
        ("Gujarat", "Kachchh", "Kutch"),
        ("Tamil Nadu", "Tuticorin", "Thoothukudi"),
        ("Odisha", "Anugul", "Angul"),
    ]
    for state, district, expected_icar_district in cases:
        ic = load_icar_data(state, district)
        default = get_default_icar_data(state, district)
        assert ic != default, f"{state}/{district} fell back to default"
        assert ic["district"].lower() == expected_icar_district.lower(), \
            f"{state}/{district} resolved to {ic['district']}, expected {expected_icar_district}"


def test_icar_alias_renamed_districts():
    """Districts renamed since 2012 should map to their ICAR-era name."""
    from utils import get_default_icar_data
    cases = [
        ("Uttar Pradesh", "Prayagraj", "Allahabad"),
        ("Uttar Pradesh", "Ayodhya", "Faizabad"),
        ("Haryana", "Gurugram", "Gurgaon"),
        ("Karnataka", "Vijayapura", "Bijapur"),
        ("Karnataka", "Belagavi", "Belgaum"),
    ]
    for state, district, expected_icar_district in cases:
        ic = load_icar_data(state, district)
        default = get_default_icar_data(state, district)
        assert ic != default, f"{state}/{district} fell back to default"
        assert ic["district"].lower() == expected_icar_district.lower(), \
            f"{state}/{district} resolved to {ic['district']}, expected {expected_icar_district}"


def test_icar_alias_state_split():
    """Telangana districts (split from AP in 2014) should resolve to AP ICAR entries."""
    from utils import get_default_icar_data
    cases = [
        ("Telangana", "Hyderabad", "Ranga Reddy"),
        ("Telangana", "Warangal", "Warangal"),
        ("Telangana", "Karimnagar", "Karimnagar"),
        ("Telangana", "Nalgonda", "Nalgonda"),
    ]
    for state, district, expected_icar_district in cases:
        ic = load_icar_data(state, district)
        default = get_default_icar_data(state, district)
        assert ic != default, f"{state}/{district} fell back to default"
        assert ic["state"] == "Andhra Pradesh", \
            f"{state}/{district} resolved to state {ic['state']}, expected Andhra Pradesh"
        assert ic["district"].lower() == expected_icar_district.lower(), \
            f"{state}/{district} resolved to {ic['district']}, expected {expected_icar_district}"


def test_icar_alias_post_2012_splits():
    """Post-2012 district splits should map to their parent district in ICAR."""
    from utils import get_default_icar_data
    cases = [
        ("Andhra Pradesh", "Eluru", "West Godavari"),
        ("Andhra Pradesh", "Kakinada", "East Godavari"),
        ("Rajasthan", "Balotra", "Barmer"),
        ("Rajasthan", "Beawar", "Ajmer"),
        ("Assam", "Majuli", "Jorhat"),
    ]
    for state, district, expected_icar_district in cases:
        ic = load_icar_data(state, district)
        default = get_default_icar_data(state, district)
        assert ic != default, f"{state}/{district} fell back to default"
        assert ic["district"].lower() == expected_icar_district.lower(), \
            f"{state}/{district} resolved to {ic['district']}, expected {expected_icar_district}"


def test_icar_fallback_for_ut():
    """UTs with no ICAR plan should fall back to default gracefully."""
    from utils import get_default_icar_data
    for state, district in [("Delhi", "New Delhi"), ("Chandigarh", "Chandigarh"),
                            ("Lakshadweep", "Lakshadweep District")]:
        ic = load_icar_data(state, district)
        default = get_default_icar_data(state, district)
        assert ic == default, f"{state}/{district} should fall back to default"
        assert "scenarios" in ic and "delayed_monsoon" in ic["scenarios"]
