"""Weather-condition coverage: the scenario classifier and advisory generator across
every risk scenario x severity, with negative guards. Uses synthetic forecast inputs so
each condition is exercised deterministically."""
import pytest

from rules import ScenarioClassifier
from advisory import AdvisoryGenerator

CLS = ScenarioClassifier()
GEN = AdvisoryGenerator()

FARMER = {"user_type": "farmer", "crop": "rice", "irrigation_status": "rainfed", "crop_stage": "not_sown"}
VEG = {**FARMER, "crop_stage": "vegetative"}

DRY4 = dict(week1_rainfall_anomaly_mm_day=-4, week2_rainfall_anomaly_mm_day=-4,
            week3_rainfall_anomaly_mm_day=-4, week4_rainfall_anomaly_mm_day=-4)
WET4 = dict(week1_rainfall_anomaly_mm_day=9, week2_rainfall_anomaly_mm_day=9,
            week3_rainfall_anomaly_mm_day=9, week4_rainfall_anomaly_mm_day=9)


def base_fc(**kw):
    """A near-normal forecast record; override fields to build a weather condition."""
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


# --------------------------------------------------------------------------- heat
@pytest.mark.parametrize("kw,risk", [
    (dict(heat_wave_warning=True, humidity_heat_index_signal="high"), "Severe"),
    (dict(heat_wave_warning=True), "Alert"),
    (dict(tmax_signal="above_normal", tmin_signal="above_normal"), "Alert"),
    (dict(tmax_signal="above_normal"), "Watch"),
])
def test_heat_stress(kw, risk):
    s = fired(base_fc(**kw))
    assert "heat_stress" in s and s["heat_stress"]["risk_level"] == risk


def test_heat_stress_absent_when_normal():
    assert "heat_stress" not in fired(base_fc())


# ------------------------------------------------------------------ delayed monsoon
@pytest.mark.parametrize("kw,risk", [
    (dict(monsoon_onset_status="not_started", rainfall_since_june_1_pct_departure=-45,
          week1_rainfall_signal="below_normal", **DRY4), "Severe"),
    (dict(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-36,
          week1_rainfall_signal="below_normal",
          week1_rainfall_anomaly_mm_day=-4, week2_rainfall_anomaly_mm_day=-4), "Alert"),
    (dict(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-26,
          week1_rainfall_signal="below_normal", week1_rainfall_anomaly_mm_day=-4), "Watch"),
])
def test_delayed_monsoon(kw, risk):
    s = fired(base_fc(**kw))
    assert "delayed_monsoon" in s and s["delayed_monsoon"]["risk_level"] == risk


@pytest.mark.parametrize("kw", [
    dict(monsoon_onset_status="normal", rainfall_since_june_1_pct_departure=-45, week1_rainfall_signal="below_normal"),
    dict(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-20, week1_rainfall_signal="below_normal"),
    dict(monsoon_onset_status="delayed", rainfall_since_june_1_pct_departure=-45, week1_rainfall_signal="near_normal"),
])
def test_delayed_monsoon_guards(kw):
    assert "delayed_monsoon" not in fired(base_fc(**kw))


# ----------------------------------------------------------------- early dry spell
@pytest.mark.parametrize("kw,risk", [
    (dict(rainfall_last_14_days_pct_departure=-55, week1_rainfall_signal="below_normal", **DRY4), "Severe"),
    (dict(rainfall_last_14_days_pct_departure=-42, week1_rainfall_signal="below_normal", week1_rainfall_anomaly_mm_day=-4), "Alert"),
    (dict(rainfall_last_14_days_pct_departure=-32, week1_rainfall_signal="below_normal", week1_rainfall_anomaly_mm_day=-4), "Watch"),
])
def test_early_dry_spell(kw, risk):
    s = fired(base_fc(**kw), VEG)
    assert "early_season_dry_spell" in s and s["early_season_dry_spell"]["risk_level"] == risk


def test_dry_spell_requires_early_crop_stage():
    kw = dict(rainfall_last_14_days_pct_departure=-55, week1_rainfall_signal="below_normal")
    assert "early_season_dry_spell" not in fired(base_fc(**kw), FARMER)   # not_sown


# ---------------------------------------------------------------- terminal drought
@pytest.mark.parametrize("stage", ["flowering", "harvesting"])
def test_terminal_drought(stage):
    kw = dict(rainfall_last_14_days_pct_departure=-55, week1_rainfall_signal="below_normal", **DRY4)
    s = fired(base_fc(**kw), {**FARMER, "crop_stage": stage})
    assert "terminal_drought" in s and s["terminal_drought"]["risk_level"] in ("Alert", "Severe")


# ---------------------------------------------------------------------- excess rain
@pytest.mark.parametrize("kw,risk", [
    (dict(heavy_rain_warning=True, **WET4), "Severe"),
    (dict(week1_rainfall_anomaly_mm_day=11), "Alert"),
    (dict(week1_rainfall_anomaly_mm_day=7), "Watch"),
])
def test_excess_rain(kw, risk):
    s = fired(base_fc(**kw))
    assert "excess_rainfall_waterlogging" in s and s["excess_rainfall_waterlogging"]["risk_level"] == risk


def test_excess_rain_recovery_after_deficit_suppressed():
    # heavy warning but only moderate anomaly after a big seasonal deficit = welcome recovery
    fc = base_fc(heavy_rain_warning=True, rainfall_since_june_1_pct_departure=-30,
                 week1_rainfall_anomaly_mm_day=5)
    assert "excess_rainfall_waterlogging" not in fired(fc)


def test_slightly_above_normal_not_flood():
    assert "excess_rainfall_waterlogging" not in fired(base_fc(week1_rainfall_anomaly_mm_day=4))


# ---------------------------------------------------------------- advisory rollup
def test_overall_risk_is_highest_scenario():
    fc = base_fc(heat_wave_warning=True, humidity_heat_index_signal="high", heavy_rain_warning=True, **WET4)
    adv = GEN.generate_advisory("S", "D", fc, {}, CLS.classify_scenarios(fc, FARMER), FARMER)
    assert adv["overall_risk"] == "Severe"


def test_no_scenarios_is_low():
    fc = base_fc()
    adv = GEN.generate_advisory("S", "D", fc, {}, CLS.classify_scenarios(fc, FARMER), FARMER)
    assert adv["overall_risk"] == "Low" and adv["main_concerns"] == []
