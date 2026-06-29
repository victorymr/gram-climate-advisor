from typing import Dict, List, Any, Tuple

class ScenarioClassifier:
    """Classifies climate risk scenarios based on forecast data and user context."""
    
    def __init__(self):
        self.scenario_rules = {
            "heat_stress": self._classify_heat_stress,
            "delayed_monsoon": self._classify_delayed_monsoon,
            "early_season_dry_spell": self._classify_early_season_dry_spell,
            "mid_season_break": self._classify_mid_season_break,
            "terminal_drought": self._classify_terminal_drought,
            "excess_rainfall_waterlogging": self._classify_excess_rainfall
        }
    
    def classify_scenarios(self, forecast_data: Dict[str, Any], user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Classify all applicable scenarios for the given forecast and user context."""
        scenarios = []
        
        for scenario_name, classifier_func in self.scenario_rules.items():
            scenario_result = classifier_func(forecast_data, user_context)
            if scenario_result:
                scenarios.append(scenario_result)
        
        # Sort by risk level (Severe > Alert > Watch > Low)
        risk_order = {"Severe": 4, "Alert": 3, "Watch": 2, "Low": 1}
        scenarios.sort(key=lambda x: risk_order.get(x["risk_level"], 0), reverse=True)
        
        return scenarios
    
    def _get_weekly_trajectory(self, forecast: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the 4-week rainfall anomaly trajectory and derived flags."""
        wk1 = forecast.get("week1_rainfall_anomaly_mm_day", 0.0)
        wk2 = forecast.get("week2_rainfall_anomaly_mm_day", 0.0)
        wk3 = forecast.get("week3_rainfall_anomaly_mm_day", 0.0)
        wk4 = forecast.get("week4_rainfall_anomaly_mm_day", 0.0)
        
        anomalies = [wk1, wk2, wk3, wk4]
        below_count = sum(1 for a in anomalies if a <= -3.0)
        above_count = sum(1 for a in anomalies if a >= 3.0)
        avg_anomaly = sum(anomalies) / 4.0
        
        # Is the outlook drying or wetting over weeks 2-4?
        wk234_avg = (wk2 + wk3 + wk4) / 3.0
        relief_coming = (wk1 <= -3.0 and wk234_avg > -1.0)  # dry now but improving
        drying_ahead = (wk1 >= -1.0 and wk234_avg <= -3.0)   # ok now but drying
        persistent_dry = below_count >= 3
        persistent_wet = above_count >= 3
        
        return {
            "anomalies": anomalies,
            "wk1": wk1, "wk2": wk2, "wk3": wk3, "wk4": wk4,
            "avg_anomaly": avg_anomaly,
            "wk234_avg": wk234_avg,
            "below_count": below_count,
            "above_count": above_count,
            "relief_coming": relief_coming,
            "drying_ahead": drying_ahead,
            "persistent_dry": persistent_dry,
            "persistent_wet": persistent_wet,
        }
    
    def _classify_heat_stress(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify heat stress scenario."""
        trigger_conditions = [
            forecast.get("heat_wave_warning", False),
            forecast.get("tmax_signal") == "above_normal",
            forecast.get("tmin_signal") == "above_normal", 
            forecast.get("humidity_heat_index_signal") == "high"
        ]
        
        if not any(trigger_conditions):
            return None
        
        # Determine risk level
        if forecast.get("heat_wave_warning", False) and forecast.get("humidity_heat_index_signal") == "high":
            risk_level = "Severe"
        elif forecast.get("heat_wave_warning", False) or (
            forecast.get("tmax_signal") == "above_normal" and forecast.get("tmin_signal") == "above_normal"
        ):
            risk_level = "Alert"
        else:
            risk_level = "Watch"
        
        # Determine confidence
        confidence = self._calculate_confidence(forecast, "heat_stress")
        
        return {
            "scenario": "heat_stress",
            "display_name": "Heat stress",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_heat_stress_reasons(forecast),
            "source_layer": ["IMD forecast products"]
        }
    
    def _classify_delayed_monsoon(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify delayed monsoon scenario."""
        monsoon_status = forecast.get("monsoon_onset_status", "normal")
        rainfall_departure = forecast.get("rainfall_since_june_1_pct_departure", 0)
        week1_signal = forecast.get("week1_rainfall_signal", "near_normal")
        traj = self._get_weekly_trajectory(forecast)
        
        trigger_conditions = [
            monsoon_status in ["not_started", "delayed"],
            rainfall_departure <= -25,
            week1_signal == "below_normal"
        ]
        
        if not all(trigger_conditions):
            return None
        
        # Determine risk level using full 4-week outlook
        if traj["persistent_dry"] and rainfall_departure <= -40:
            risk_level = "Severe"
        elif traj["below_count"] >= 2 or rainfall_departure <= -35:
            risk_level = "Alert"
        elif traj["relief_coming"]:
            risk_level = "Watch"  # dry now but rain expected — lower severity
        else:
            risk_level = "Watch"
        
        confidence = self._calculate_confidence(forecast, "delayed_monsoon")
        
        return {
            "scenario": "delayed_monsoon",
            "display_name": "Delayed monsoon / delayed sowing",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_delayed_monsoon_reasons(forecast),
            "source_layer": ["IMD rainfall status", "IMD extended range forecast", "ICAR district contingency plan"]
        }
    
    def _classify_early_season_dry_spell(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify early season dry spell scenario."""
        crop_stage = user_context.get("crop_stage", "")
        rainfall_14d = forecast.get("rainfall_last_14_days_pct_departure", 0)
        week1_signal = forecast.get("week1_rainfall_signal", "near_normal")
        traj = self._get_weekly_trajectory(forecast)
        
        if crop_stage not in ["recently_sown", "vegetative"]:
            return None
        
        trigger_conditions = [
            rainfall_14d <= -30,
            week1_signal == "below_normal"
        ]
        
        if not all(trigger_conditions):
            return None
        
        # Determine risk level — modulated by multi-week outlook
        if rainfall_14d <= -50 and traj["persistent_dry"]:
            risk_level = "Severe"
        elif rainfall_14d <= -50 and traj["relief_coming"]:
            risk_level = "Alert"  # severe deficit but rain expected
        elif rainfall_14d <= -40:
            risk_level = "Alert"
        elif traj["relief_coming"]:
            risk_level = "Watch"  # moderate deficit with relief ahead
        else:
            risk_level = "Watch"
        
        confidence = self._calculate_confidence(forecast, "early_season_dry_spell")
        
        return {
            "scenario": "early_season_dry_spell",
            "display_name": "Early-season dry spell",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_early_season_dry_spell_reasons(forecast, user_context),
            "source_layer": ["IMD observed rainfall", "IMD forecast", "ICAR district contingency plan"]
        }
    
    def _classify_mid_season_break(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify mid-season monsoon break scenario."""
        crop_stage = user_context.get("crop_stage", "")
        monsoon_status = forecast.get("monsoon_onset_status", "normal")
        rainfall_14d = forecast.get("rainfall_last_14_days_pct_departure", 0)
        week1_signal = forecast.get("week1_rainfall_signal", "near_normal")
        traj = self._get_weekly_trajectory(forecast)
        
        if crop_stage not in ["vegetative", "flowering"]:
            return None
        
        if monsoon_status not in ["active", "weak"]:
            return None
        
        trigger_conditions = [
            rainfall_14d <= -40,
            week1_signal == "below_normal"
        ]
        
        if not all(trigger_conditions):
            return None
        
        # Determine risk level — multi-week outlook matters for break duration
        if traj["persistent_dry"] and rainfall_14d <= -60:
            risk_level = "Severe"
        elif traj["below_count"] >= 2 or rainfall_14d <= -50:
            risk_level = "Alert"
        elif traj["relief_coming"]:
            risk_level = "Watch"  # break likely short-lived
        else:
            risk_level = "Watch"
        
        confidence = self._calculate_confidence(forecast, "mid_season_break")
        
        return {
            "scenario": "mid_season_break",
            "display_name": "Mid-season monsoon break",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_mid_season_break_reasons(forecast, user_context),
            "source_layer": ["IMD observed rainfall", "IMD forecast", "ICAR district contingency plan"]
        }
    
    def _classify_terminal_drought(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify terminal drought scenario."""
        crop_stage = user_context.get("crop_stage", "")
        rainfall_14d = forecast.get("rainfall_last_14_days_pct_departure", 0)
        week1_signal = forecast.get("week1_rainfall_signal", "near_normal")
        traj = self._get_weekly_trajectory(forecast)
        
        if crop_stage not in ["flowering", "harvesting"]:
            return None
        
        trigger_conditions = [
            rainfall_14d <= -40,
            week1_signal == "below_normal"
        ]
        
        if not all(trigger_conditions):
            return None
        
        # Determine risk level — persistent dry across 4 weeks is very serious
        if traj["persistent_dry"] and rainfall_14d <= -50:
            risk_level = "Severe"
        elif traj["below_count"] >= 2 or rainfall_14d <= -50:
            risk_level = "Alert"
        elif traj["relief_coming"]:
            risk_level = "Watch"  # some rain expected — may not be too late
        else:
            risk_level = "Watch"
        
        confidence = self._calculate_confidence(forecast, "terminal_drought")
        
        return {
            "scenario": "terminal_drought",
            "display_name": "Terminal drought / early withdrawal risk",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_terminal_drought_reasons(forecast, user_context),
            "source_layer": ["IMD observed rainfall", "IMD forecast", "ICAR district contingency plan"]
        }
    
    def _classify_excess_rainfall(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Classify excess rainfall/waterlogging scenario.
        
        Key design decisions:
        - A slight above-normal anomaly (+3 mm/day) is NOT a flood risk,
          especially after a dry spell — it's welcome recovery rain.
        - Only trigger at +7 mm/day anomaly or with an explicit heavy_rain_warning.
        - Suppress entirely if seasonal deficit is large and anomaly is moderate
          (rain after drought is beneficial, not a risk).
        """
        heavy_rain = forecast.get("heavy_rain_warning", False)
        traj = self._get_weekly_trajectory(forecast)
        seasonal_departure = forecast.get("rainfall_since_june_1_pct_departure", 0)
        
        # Use actual mm/day anomaly, not just the categorical signal
        wk1_anomaly = traj["wk1"]
        max_anomaly = max(traj["anomalies"])
        
        # Moderate above-normal rain after a seasonal deficit is recovery, not risk
        is_recovery_rain = (seasonal_departure <= -20 and max_anomaly < 7.0)
        
        # Trigger thresholds: +7 mm/day anomaly OR explicit heavy rain warning
        anomaly_trigger = max_anomaly >= 7.0
        
        if not (heavy_rain or anomaly_trigger) or is_recovery_rain:
            return None
        
        # Determine risk level
        if heavy_rain and traj["persistent_wet"]:
            risk_level = "Severe"
        elif heavy_rain and max_anomaly >= 7.0:
            risk_level = "Severe"
        elif heavy_rain or max_anomaly >= 10.0:
            risk_level = "Alert"
        elif traj["persistent_wet"]:
            risk_level = "Alert"
        else:
            risk_level = "Watch"
        
        confidence = self._calculate_confidence(forecast, "excess_rainfall_waterlogging")
        
        return {
            "scenario": "excess_rainfall_waterlogging",
            "display_name": "Excess rainfall / waterlogging",
            "risk_level": risk_level,
            "confidence": confidence,
            "reasons": self._get_excess_rainfall_reasons(forecast),
            "source_layer": ["IMD heavy rainfall warnings", "IMD extended range forecast"]
        }
    
    def _calculate_confidence(self, forecast: Dict[str, Any], scenario: str) -> str:
        """Calculate confidence based on forecast lead time.
        
        Extended range forecast skill degrades with lead time:
        - Week 1-2 signals → High confidence
        - Week 3-4 signals only → Medium confidence
        
        For scenarios that also use observed data (rainfall departure,
        heat wave warnings), the observed component is always High.
        """
        traj = self._get_weekly_trajectory(forecast)
        
        if scenario in ["delayed_monsoon", "early_season_dry_spell", "mid_season_break", "terminal_drought"]:
            # These scenarios require week1 below_normal as a trigger,
            # so they always have a Week 1 signal → High
            return "High"
        elif scenario == "heat_stress":
            # tmax_signal is Week 1 based → High for heat wave or Week 1 signal
            if forecast.get("heat_wave_warning", False):
                return "High"
            elif forecast.get("tmax_signal") == "above_normal":
                return "High"  # Week 1 tmax signal
            else:
                return "Medium"
        elif scenario == "excess_rainfall_waterlogging":
            # Check whether the triggering anomaly is in Week 1-2 vs Week 3-4
            wk12_max = max(traj["wk1"], traj["wk2"])
            wk34_max = max(traj["wk3"], traj["wk4"])
            if forecast.get("heavy_rain_warning", False):
                return "High"  # official warning = high confidence
            elif wk12_max >= 7.0:
                return "High"  # triggered by Week 1-2
            elif wk34_max >= 7.0:
                return "Medium"  # triggered by Week 3-4 only
            else:
                return "Medium"
        else:
            return "Medium"
    
    def _get_heat_stress_reasons(self, forecast: Dict[str, Any]) -> List[str]:
        """Get reasons for heat stress classification."""
        reasons = []
        if forecast.get("heat_wave_warning", False):
            reasons.append("Heat wave warning in effect")
        if forecast.get("tmax_signal") == "above_normal":
            reasons.append("Above-normal maximum temperatures")
        if forecast.get("tmin_signal") == "above_normal":
            reasons.append("Above-normal minimum temperatures")
        if forecast.get("humidity_heat_index_signal") == "high":
            reasons.append("High humidity and heat index")
        return reasons
    
    def _get_delayed_monsoon_reasons(self, forecast: Dict[str, Any]) -> List[str]:
        """Get reasons for delayed monsoon classification."""
        reasons = []
        departure = forecast.get("rainfall_since_june_1_pct_departure", 0)
        reasons.append(f"Rainfall since June 1 is {abs(departure)}% {'below' if departure < 0 else 'above'} normal")
        
        if forecast.get("monsoon_onset_status") == "delayed":
            reasons.append("Monsoon onset status is delayed")
        elif forecast.get("monsoon_onset_status") == "not_started":
            reasons.append("Monsoon has not started yet")
        
        traj = self._get_weekly_trajectory(forecast)
        reasons.append(self._format_weekly_outlook(traj))
        
        if traj["relief_coming"]:
            reasons.append("Some rainfall improvement expected in weeks 2-4")
        elif traj["persistent_dry"]:
            reasons.append("Dry conditions expected to persist across all 4 weeks")
        
        return reasons
    
    def _get_early_season_dry_spell_reasons(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> List[str]:
        """Get reasons for early season dry spell classification."""
        reasons = []
        departure = forecast.get("rainfall_last_14_days_pct_departure", 0)
        reasons.append(f"Rainfall in last 14 days is {abs(departure)}% {'below' if departure < 0 else 'above'} normal")
        reasons.append(f"Crop stage: {user_context.get('crop_stage', 'unknown')}")
        
        traj = self._get_weekly_trajectory(forecast)
        reasons.append(self._format_weekly_outlook(traj))
        
        if traj["relief_coming"]:
            reasons.append("Rainfall improvement expected in weeks 2-4 — hold off on drastic measures")
        elif traj["persistent_dry"]:
            reasons.append("Dry conditions expected to persist across all 4 weeks")
        
        return reasons
    
    def _get_mid_season_break_reasons(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> List[str]:
        """Get reasons for mid-season break classification."""
        reasons = []
        departure = forecast.get("rainfall_last_14_days_pct_departure", 0)
        reasons.append(f"Rainfall in last 14 days is {abs(departure)}% {'below' if departure < 0 else 'above'} normal")
        reasons.append(f"Crop stage: {user_context.get('crop_stage', 'unknown')}")
        reasons.append(f"Monsoon status: {forecast.get('monsoon_onset_status', 'unknown')}")
        
        traj = self._get_weekly_trajectory(forecast)
        reasons.append(self._format_weekly_outlook(traj))
        
        if traj["relief_coming"]:
            reasons.append("Break likely short-lived — rainfall improvement expected in weeks 2-4")
        elif traj["persistent_dry"]:
            reasons.append("Extended break expected — dry conditions across all 4 weeks")
        
        return reasons
    
    def _get_terminal_drought_reasons(self, forecast: Dict[str, Any], user_context: Dict[str, Any]) -> List[str]:
        """Get reasons for terminal drought classification."""
        reasons = []
        departure = forecast.get("rainfall_last_14_days_pct_departure", 0)
        reasons.append(f"Rainfall in last 14 days is {abs(departure)}% {'below' if departure < 0 else 'above'} normal")
        reasons.append(f"Crop stage: {user_context.get('crop_stage', 'unknown')} (critical reproductive phase)")
        
        traj = self._get_weekly_trajectory(forecast)
        reasons.append(self._format_weekly_outlook(traj))
        
        if traj["persistent_dry"]:
            reasons.append("No rainfall recovery expected in the 4-week outlook")
        elif traj["relief_coming"]:
            reasons.append("Some rainfall expected in weeks 2-4 — may provide partial relief")
        
        return reasons
    
    def _get_excess_rainfall_reasons(self, forecast: Dict[str, Any]) -> List[str]:
        """Get reasons for excess rainfall classification."""
        reasons = []
        if forecast.get("heavy_rain_warning", False):
            reasons.append("Heavy rainfall warning in effect")
        
        traj = self._get_weekly_trajectory(forecast)
        max_anom = max(traj["anomalies"])
        reasons.append(f"Peak rainfall anomaly: +{max_anom:.0f} mm/day above normal")
        reasons.append(self._format_weekly_outlook(traj))
        
        if traj["persistent_wet"]:
            reasons.append("Above-normal rainfall expected to persist across multiple weeks")
        
        return reasons
    
    def _format_weekly_outlook(self, traj: Dict[str, Any]) -> str:
        """Format a human-readable 4-week rainfall outlook string."""
        def _signal(val):
            if val >= 3.0:
                return f"+{val:.0f} (above)"
            elif val <= -3.0:
                return f"{val:.0f} (below)"
            else:
                return f"{val:+.0f} (near normal)"
        
        return (f"4-week outlook (mm/day anomaly): "
                f"Wk1={_signal(traj['wk1'])}, "
                f"Wk2={_signal(traj['wk2'])}, "
                f"Wk3={_signal(traj['wk3'])}, "
                f"Wk4={_signal(traj['wk4'])}")
