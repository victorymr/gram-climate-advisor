"""End-to-end coverage across areas x contexts: for a stratified sample of districts from
every geographic zone, generate advisories under a matrix of user contexts and assert they
are well-formed and never emit guardrail-violating language."""
import csv
from pathlib import Path

import pytest

from rules import ScenarioClassifier
from advisory import AdvisoryGenerator
from utils import load_district_data, load_icar_data

ROOT = Path(__file__).resolve().parent.parent
COORDS = list(csv.DictReader(open(ROOT / "data" / "district_coordinates.csv", encoding="utf-8")))

# stratified: up to 3 districts from each region/zone -> geographic coverage
_by_zone = {}
for r in COORDS:
    _by_zone.setdefault(r["region"], []).append((r["state"], r["district"]))
SAMPLE = [d for zone in sorted(_by_zone) for d in _by_zone[zone][:3]]

CONTEXTS = [
    {"user_type": "farmer", "crop": "rice", "irrigation_status": "rainfed", "crop_stage": cs}
    for cs in ("not_sown", "vegetative", "flowering", "harvesting")
] + [
    {"user_type": ut, "crop": None, "irrigation_status": "unknown", "crop_stage": None}
    for ut in ("livestock_owner", "outdoor_worker", "village_official", "health_worker")
]

CLS = ScenarioClassifier()
GEN = AdvisoryGenerator()

REQUIRED_KEYS = ["overall_risk", "main_concerns", "forecast_summary", "extended_outlook",
                 "actions_do_now", "actions_prepare", "actions_avoid", "general_guidance",
                 "source_notes", "disclaimer"]
# phrases the system must never state (README guardrails)
FORBIDDEN = ["monsoon will fail", "do not plant", "crop will fail",
             "official government advice", "medical advice"]


@pytest.mark.parametrize("state,district", SAMPLE)
def test_advisory_wellformed_all_contexts(state, district):
    fc = load_district_data(state, district)
    ic = load_icar_data(state, district)
    for ctx in CONTEXTS:
        scenarios = CLS.classify_scenarios(fc, ctx)
        adv = GEN.generate_advisory(state, district, fc, ic, scenarios, ctx)

        for k in REQUIRED_KEYS:
            assert k in adv, (state, district, ctx["user_type"], f"missing {k}")
        assert adv["overall_risk"] in ("Low", "Watch", "Alert", "Severe")
        for k in ("actions_do_now", "actions_prepare", "actions_avoid", "general_guidance", "main_concerns"):
            assert isinstance(adv[k], list)
        assert adv["extended_outlook"]["weeks"], (state, district)

        text = " ".join(str(x) for x in (
            adv["actions_do_now"] + adv["actions_prepare"] + adv["actions_avoid"]
            + adv["general_guidance"] + [adv["forecast_summary"]])).lower()
        for phrase in FORBIDDEN:
            assert phrase not in text, (state, district, ctx["user_type"], f"guardrail: '{phrase}'")


def test_sample_spans_all_zones():
    assert len(_by_zone) >= 6, f"expected many zones, got {sorted(_by_zone)}"
    assert len(SAMPLE) >= 18
