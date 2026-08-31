"""Skill-calibrated confidence: the forecast_skill.json loader and how the rule engine
uses it. The scenario confidence must follow the measured skill of the forecast weeks a
classification rests on (weakest contributing week), not a fixed lead-time guess."""
import pytest

import rules as rules_mod
from rules import ScenarioClassifier
from skill import (TIERS, category_hit, describe, district_zone, load_skill, weakest,
                   week_skill, week_tier)

CLS = ScenarioClassifier()
SKILL = load_skill()
FARMER = {"user_type": "farmer", "crop": "rice", "irrigation_status": "rainfed", "crop_stage": "not_sown"}
ZONES = {"Central India", "East India", "North India", "North-West India",
         "Northeast India", "South India", "West India", "Islands"}


def base_fc(**kw):
    fc = dict(
        state="Test", district="Test", forecast_date="2026-06-29",
        rainfall_since_june_1_pct_departure=0, rainfall_last_7_days_pct_departure=0,
        rainfall_last_14_days_pct_departure=0, monsoon_onset_status="normal",
        week1_rainfall_signal="near_normal", week2_rainfall_signal="near_normal",
        week3_4_rainfall_signal="near_normal", seasonal_monsoon_context="normal",
        tmax_signal="near_normal", tmin_signal="near_normal",
        heat_wave_warning=False, heavy_rain_warning=False, humidity_heat_index_signal="normal",
        week1_rainfall_anomaly_mm_day=0.0, week2_rainfall_anomaly_mm_day=0.0,
        week3_rainfall_anomaly_mm_day=0.0, week4_rainfall_anomaly_mm_day=0.0,
        week1_tmax_anomaly_degC=0.0,
    )
    fc.update(kw)
    return fc


def fired(fc, ctx=FARMER):
    return {s["scenario"]: s for s in CLS.classify_scenarios(fc, ctx)}


# ----------------------------------------------------------------- skill table
def test_skill_table_present_and_decays_with_lead():
    assert SKILL and SKILL["national"]["precip"] and SKILL["national"]["t2m"]
    rank = {"High": 3, "Medium": 2, "Low": 1}
    for var in ("precip", "t2m"):
        # data assertion kept loose: the exact week-1 tier moves with the backtest sample
        # (25-init 2021-25: High; pooled with the 2000-19 reforecast: precip 0.496 -> Medium)
        assert rank[week_tier(SKILL, var, 1)] >= 2
        assert week_tier(SKILL, var, 5) == "Low"
        assert rank[week_tier(SKILL, var, 1)] >= rank[week_tier(SKILL, var, 5)]
        accs = [week_skill(SKILL, var, w)["acc"] for w in (1, 2, 3, 4, 5)]
        assert accs[0] == max(accs) and accs[-1] < accs[0]


def test_zone_cell_or_national_fallback():
    assert week_skill(SKILL, "precip", 1, "South India")["scope"] == "South India"
    assert week_skill(SKILL, "precip", 1, "Atlantis")["scope"] == "India"
    assert week_skill(SKILL, "precip", 1, None)["scope"] == "India"
    assert week_skill(None, "precip", 1) is None and week_tier(None, "precip", 1) is None


def test_category_hit_rates_beat_chance_at_week_1():
    for var, cat in (("precip", "below"), ("precip", "above"), ("t2m", "above")):
        hit, base = category_hit(SKILL, var, 1, cat)
        assert hit > base


def test_weakest_tier():
    assert weakest(["High", "Low", "Medium"]) == "Low"
    assert weakest(["High", None]) == "High"
    assert weakest([None, None]) is None
    assert tuple(TIERS) == ("Low", "Medium", "High")


def test_describe_mentions_week_tier_and_category():
    line = describe(SKILL, "precip", 3, None, "below")
    assert line.startswith("Week 3 rainfall: Low confidence")
    assert "drier than normal" in line and "chance" in line


def test_district_zone_lookup():
    assert district_zone("Bihar", "Patna") in ZONES
    assert district_zone("bihar", "PATNA") == district_zone("Bihar", "Patna")
    assert district_zone("Nowhere", "Nowhere") is None


# --------------------------------------------------------- rule-engine confidence
def test_week1_only_evidence_takes_week1_tier():
    # Alert justified by the observed departure alone -> only week 1 is forecast evidence,
    # so confidence must equal the table's week-1 tier (whatever the current table says).
    s = fired(base_fc(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-40,
                      week1_rainfall_signal="below_normal", week1_rainfall_anomaly_mm_day=-4))
    dm = s["delayed_monsoon"]
    assert dm["risk_level"] == "Alert"
    assert dm["confidence"] == week_tier(SKILL, "precip", 1)
    assert len(dm["confidence_basis"]) == 1 and dm["confidence_basis"][0].startswith("Week 1 rainfall")


def test_escalation_by_a_later_week_takes_that_weeks_skill():
    # departure -30 is not enough for Alert on its own; below_count>=2 (weeks 1 + 3) is
    s = fired(base_fc(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-30,
                      week1_rainfall_signal="below_normal",
                      week1_rainfall_anomaly_mm_day=-4, week3_rainfall_anomaly_mm_day=-4))
    dm = s["delayed_monsoon"]
    assert dm["risk_level"] == "Alert"
    assert dm["confidence"] == weakest([week_tier(SKILL, "precip", 1), week_tier(SKILL, "precip", 3)]) == "Low"
    assert [b.split(":")[0] for b in dm["confidence_basis"]] == ["Week 1 rainfall", "Week 3 rainfall"]


def test_severe_persistent_dry_rests_on_three_weeks():
    s = fired(base_fc(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-45,
                      week1_rainfall_signal="below_normal",
                      week1_rainfall_anomaly_mm_day=-4, week2_rainfall_anomaly_mm_day=-4,
                      week3_rainfall_anomaly_mm_day=-4, week4_rainfall_anomaly_mm_day=-4))
    dm = s["delayed_monsoon"]
    assert dm["risk_level"] == "Severe"
    assert dm["confidence"] == weakest(week_tier(SKILL, "precip", w) for w in (1, 2, 3))
    assert len(dm["confidence_basis"]) == 3


def test_official_warnings_are_high():
    hs = fired(base_fc(heat_wave_warning=True))["heat_stress"]
    assert hs["confidence"] == "High" and "Official" in hs["confidence_basis"][0]
    ex = fired(base_fc(heavy_rain_warning=True, week1_rainfall_anomaly_mm_day=8.0))
    assert ex["excess_rainfall_waterlogging"]["confidence"] == "High"


def test_heat_signal_uses_week1_temperature_skill():
    hs = fired(base_fc(tmax_signal="above_normal"))["heat_stress"]
    assert hs["confidence"] == week_tier(SKILL, "t2m", 1)
    assert hs["confidence_basis"][0].startswith("Week 1 temperature")


def test_excess_rain_from_a_week3_peak_uses_week3_skill():
    ex = fired(base_fc(week3_rainfall_anomaly_mm_day=8.0))["excess_rainfall_waterlogging"]
    assert ex["risk_level"] == "Watch"
    assert ex["confidence"] == week_tier(SKILL, "precip", 3) == "Low"
    assert "heavy rain" in ex["confidence_basis"][0]


def test_zone_specific_tier_for_a_real_district():
    # A real district resolves to its climate zone; the tier must match that zone's cell.
    fc = base_fc(state="Bihar", district="Patna", monsoon_onset_status="delayed",
                 rainfall_since_june_1_pct_departure=-40, week1_rainfall_signal="below_normal",
                 week1_rainfall_anomaly_mm_day=-4)
    dm = fired(fc)["delayed_monsoon"]
    zone = district_zone("Bihar", "Patna")
    assert dm["confidence"] == week_tier(SKILL, "precip", 1, zone)
    assert zone in dm["confidence_basis"][0]


def test_heuristic_fallback_without_skill_table(monkeypatch):
    monkeypatch.setattr(rules_mod, "load_skill", lambda: None)
    s = fired(base_fc(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-30,
                      week1_rainfall_signal="below_normal",
                      week1_rainfall_anomaly_mm_day=-4, week3_rainfall_anomaly_mm_day=-4))
    dm = s["delayed_monsoon"]
    assert dm["confidence"] == "High" and dm["confidence_basis"] == []
