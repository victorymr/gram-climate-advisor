#!/usr/bin/env python3
"""
Test cases for the main climate risk scenarios in Gram Climate Advisor.
This script tests the scenario classification and advisory generation.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from rules import ScenarioClassifier
from advisory import AdvisoryGenerator
from utils import load_district_data, load_icar_data

def test_delayed_monsoon_scenario():
    """Test Case 1: Delayed Monsoon"""
    print("🧪 Testing Delayed Monsoon Scenario...")
    
    # Test data for delayed monsoon
    forecast_data = {
        "rainfall_since_june_1_pct_departure": -45,
        "monsoon_onset_status": "delayed",
        "week1_rainfall_signal": "below_normal",
        "week2_rainfall_signal": "below_normal",
        "seasonal_monsoon_context": "below_normal_risk"
    }
    
    user_context = {
        "user_type": "farmer",
        "crop": "rice",
        "irrigation_status": "rainfed",
        "crop_stage": "not_sown"
    }
    
    # Classify scenarios
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(forecast_data, user_context)
    
    # Check results
    delayed_monsoon_found = False
    for scenario in scenarios:
        if scenario["scenario"] == "delayed_monsoon":
            delayed_monsoon_found = True
            print(f"   ✅ Delayed monsoon detected: {scenario['risk_level']} risk, {scenario['confidence']} confidence")
            print(f"   📝 Reasons: {'; '.join(scenario['reasons'])}")
            
            # Verify expected risk level
            expected_risk = "Severe" if forecast_data["week2_rainfall_signal"] == "below_normal" and forecast_data["rainfall_since_june_1_pct_departure"] <= -40 else "Alert"
            if scenario["risk_level"] in ["Severe", "Alert"]:
                print(f"   ✅ Risk level appropriate: {scenario['risk_level']}")
            else:
                print(f"   ⚠️  Unexpected risk level: {scenario['risk_level']}")
            break
    
    if not delayed_monsoon_found:
        print("   ❌ Delayed monsoon scenario not detected")
        return False
    
    return True

def test_heat_stress_scenario():
    """Test Case 2: Heat Stress"""
    print("\n🧪 Testing Heat Stress Scenario...")
    
    # Test data for heat stress
    forecast_data = {
        "tmax_signal": "above_normal",
        "tmin_signal": "above_normal", 
        "humidity_heat_index_signal": "high",
        "heat_wave_warning": True
    }
    
    user_context = {
        "user_type": "outdoor_worker",
        "crop": None,
        "irrigation_status": "unknown",
        "crop_stage": None
    }
    
    # Classify scenarios
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(forecast_data, user_context)
    
    # Check results
    heat_stress_found = False
    for scenario in scenarios:
        if scenario["scenario"] == "heat_stress":
            heat_stress_found = True
            print(f"   ✅ Heat stress detected: {scenario['risk_level']} risk, {scenario['confidence']} confidence")
            print(f"   📝 Reasons: {'; '.join(scenario['reasons'])}")
            
            # Should be Severe with heat wave warning + high humidity
            if scenario["risk_level"] == "Severe":
                print(f"   ✅ Risk level appropriate: {scenario['risk_level']}")
            else:
                print(f"   ⚠️  Expected Severe risk, got: {scenario['risk_level']}")
            break
    
    if not heat_stress_found:
        print("   ❌ Heat stress scenario not detected")
        return False
    
    return True

def test_mid_season_break_scenario():
    """Test Case 3: Mid-Season Break"""
    print("\n🧪 Testing Mid-Season Break Scenario...")
    
    # Test data for mid-season break
    forecast_data = {
        "monsoon_onset_status": "active",
        "rainfall_last_14_days_pct_departure": -50,
        "week1_rainfall_signal": "below_normal",
        "week2_rainfall_signal": "below_normal"
    }
    
    user_context = {
        "user_type": "farmer",
        "crop": "rice",
        "irrigation_status": "partial_irrigation",
        "crop_stage": "flowering"
    }
    
    # Classify scenarios
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(forecast_data, user_context)
    
    # Check results
    mid_season_found = False
    for scenario in scenarios:
        if scenario["scenario"] == "mid_season_break":
            mid_season_found = True
            print(f"   ✅ Mid-season break detected: {scenario['risk_level']} risk, {scenario['confidence']} confidence")
            print(f"   📝 Reasons: {'; '.join(scenario['reasons'])}")
            
            # Should be Alert or Severe with these conditions
            if scenario["risk_level"] in ["Alert", "Severe"]:
                print(f"   ✅ Risk level appropriate: {scenario['risk_level']}")
            else:
                print(f"   ⚠️  Expected Alert/Severe risk, got: {scenario['risk_level']}")
            break
    
    if not mid_season_found:
        print("   ❌ Mid-season break scenario not detected")
        return False
    
    return True

def test_excess_rainfall_scenario():
    """Test Case 4: Excess Rainfall"""
    print("\n🧪 Testing Excess Rainfall Scenario...")
    
    # Test data for excess rainfall
    forecast_data = {
        "heavy_rain_warning": True,
        "week1_rainfall_signal": "above_normal"
    }
    
    user_context = {
        "user_type": "farmer",
        "crop": "cotton",
        "irrigation_status": "assured_irrigation",
        "crop_stage": "vegetative"
    }
    
    # Classify scenarios
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(forecast_data, user_context)
    
    # Check results
    excess_rain_found = False
    for scenario in scenarios:
        if scenario["scenario"] == "excess_rainfall_waterlogging":
            excess_rain_found = True
            print(f"   ✅ Excess rainfall detected: {scenario['risk_level']} risk, {scenario['confidence']} confidence")
            print(f"   📝 Reasons: {'; '.join(scenario['reasons'])}")
            
            # Should be Severe with both conditions met
            if scenario["risk_level"] == "Severe":
                print(f"   ✅ Risk level appropriate: {scenario['risk_level']}")
            else:
                print(f"   ⚠️  Expected Severe risk, got: {scenario['risk_level']}")
            break
    
    if not excess_rain_found:
        print("   ❌ Excess rainfall scenario not detected")
        return False
    
    return True

def test_advisory_generation():
    """Test complete advisory generation"""
    print("\n🧪 Testing Advisory Generation...")
    
    # Use real data from Gaya, Bihar
    state = "Bihar"
    district = "Gaya"
    
    try:
        # Load data
        forecast_data = load_district_data(state, district)
        icar_data = load_icar_data(state, district)
        
        user_context = {
            "user_type": "farmer",
            "crop": "rice",
            "irrigation_status": "rainfed",
            "crop_stage": "not_sown"
        }
        
        # Classify scenarios
        classifier = ScenarioClassifier()
        scenarios = classifier.classify_scenarios(forecast_data, user_context)
        
        # Generate advisory
        advisor = AdvisoryGenerator()
        advisory = advisor.generate_advisory(state, district, forecast_data, icar_data, scenarios, user_context)
        
        # Check advisory structure
        required_fields = [
            "state", "district", "overall_risk", "main_concerns",
            "forecast_summary", "scenarios", "actions_do_now",
            "actions_prepare", "actions_avoid", "source_notes", "disclaimer"
        ]
        
        missing_fields = []
        for field in required_fields:
            if field not in advisory:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"   ❌ Missing advisory fields: {missing_fields}")
            return False
        
        print(f"   ✅ Advisory generated successfully")
        print(f"   📍 Location: {advisory['state']}, {advisory['district']}")
        print(f"   🎯 Overall Risk: {advisory['overall_risk']}")
        print(f"   📊 Scenarios: {len(advisory['scenarios'])}")
        print(f"   📋 Actions: {len(advisory['actions_do_now'])} do now, {len(advisory['actions_prepare'])} prepare, {len(advisory['actions_avoid'])} avoid")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Advisory generation failed: {str(e)}")
        return False

def test_edge_cases():
    """Test edge cases and error conditions"""
    print("\n🧪 Testing Edge Cases...")
    
    # Test with no scenarios (normal conditions)
    normal_forecast = {
        "rainfall_since_june_1_pct_departure": 5,
        "monsoon_onset_status": "normal",
        "week1_rainfall_signal": "near_normal",
        "week2_rainfall_signal": "near_normal",
        "tmax_signal": "near_normal",
        "tmin_signal": "near_normal",
        "heat_wave_warning": False,
        "heavy_rain_warning": False,
        "humidity_heat_index_signal": "normal"
    }
    
    user_context = {
        "user_type": "farmer",
        "crop": "rice",
        "irrigation_status": "rainfed",
        "crop_stage": "vegetative"
    }
    
    classifier = ScenarioClassifier()
    scenarios = classifier.classify_scenarios(normal_forecast, user_context)
    
    if len(scenarios) == 0:
        print("   ✅ No scenarios detected for normal conditions")
    else:
        print(f"   ⚠️  Unexpected scenarios detected: {[s['scenario'] for s in scenarios]}")
    
    # Test with missing user context
    minimal_context = {"user_type": "farmer"}
    scenarios = classifier.classify_scenarios(normal_forecast, minimal_context)
    print(f"   ✅ Handled minimal user context: {len(scenarios)} scenarios")
    
    return True

def run_all_tests():
    """Run all test cases"""
    print("🌾 Gram Climate Advisor - Test Suite")
    print("=" * 50)
    
    tests = [
        test_delayed_monsoon_scenario,
        test_heat_stress_scenario,
        test_mid_season_break_scenario,
        test_excess_rainfall_scenario,
        test_advisory_generation,
        test_edge_cases
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"   ❌ Test failed with exception: {str(e)}")
            failed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! The system is working correctly.")
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
