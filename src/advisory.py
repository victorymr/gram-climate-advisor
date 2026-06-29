from typing import Dict, List, Any
from datetime import datetime

class AdvisoryGenerator:
    """Generates climate risk advisories based on scenarios and user context."""
    
    def __init__(self):
        self.action_library = self._load_action_library()
    
    def generate_advisory(self, state: str, district: str, forecast_data: Dict[str, Any], 
                         icar_data: Dict[str, Any], scenarios: List[Dict[str, Any]], 
                         user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a complete advisory for the given inputs."""
        
        # Determine overall risk level
        overall_risk = self._calculate_overall_risk(scenarios)
        
        # Generate forecast summary
        forecast_summary = self._generate_forecast_summary(forecast_data, scenarios)
        
        # Get main concerns
        main_concerns = [s['display_name'] for s in scenarios]
        
        # Generate actions based on scenarios and user context
        actions = self._generate_actions(scenarios, icar_data, user_context, forecast_data)
        
        # Generate extended 4-week outlook
        extended_outlook = self._generate_extended_outlook(forecast_data)
        
        # Create advisory object
        advisory = {
            "state": state,
            "district": district,
            "forecast_date": forecast_data.get("forecast_date", datetime.now().strftime("%Y-%m-%d")),
            "overall_risk": overall_risk,
            "main_concerns": main_concerns,
            "forecast_summary": forecast_summary,
            "extended_outlook": extended_outlook,
            "scenarios": scenarios,
            "actions_do_now": actions["do_now"],
            "actions_prepare": actions["prepare"],
            "actions_avoid": actions["avoid"],
            "general_guidance": actions["general_guidance"],
            "source_notes": {
                "forecast_source": "IMD forecast products",
                "agriculture_source": "ICAR/CRIDA district contingency plan and local agromet guidance where available",
                "health_source": "NDMA / state heat action / health guidance where available",
                "last_updated": datetime.now().strftime("%Y-%m-%d")
            },
            "disclaimer": "This advisory is for planning support only. Follow official IMD warnings, local government instructions, local agricultural extension advice, and medical guidance."
        }
        
        return advisory
    
    def _calculate_overall_risk(self, scenarios: List[Dict[str, Any]]) -> str:
        """Calculate overall risk level from individual scenario risks."""
        if not scenarios:
            return "Low"
        
        risk_order = {"Severe": 4, "Alert": 3, "Watch": 2, "Low": 1}
        highest_risk = max(scenarios, key=lambda x: risk_order.get(x["risk_level"], 0))
        
        return highest_risk["risk_level"]
    
    def _generate_forecast_summary(self, forecast: Dict[str, Any], scenarios: List[Dict[str, Any]]) -> str:
        """Generate a plain-language forecast summary."""
        summary_parts = []
        
        # Rainfall situation
        rainfall_departure = forecast.get("rainfall_since_june_1_pct_departure", 0)
        if rainfall_departure < -20:
            summary_parts.append(f"Rainfall has been {abs(rainfall_departure)}% below normal since June 1")
        elif rainfall_departure > 20:
            summary_parts.append(f"Rainfall has been {rainfall_departure}% above normal since June 1")
        else:
            summary_parts.append("Rainfall has been near normal since June 1")
        
        # 4-week rainfall outlook
        wk1 = forecast.get("week1_rainfall_anomaly_mm_day", 0.0)
        wk2 = forecast.get("week2_rainfall_anomaly_mm_day", 0.0)
        wk3 = forecast.get("week3_rainfall_anomaly_mm_day", 0.0)
        wk4 = forecast.get("week4_rainfall_anomaly_mm_day", 0.0)
        
        def _sig(v):
            if v >= 3.0: return "above normal"
            if v <= -3.0: return "below normal"
            return "near normal"
        
        all_below = all(a <= -3.0 for a in [wk1, wk2, wk3, wk4])
        all_above = all(a >= 3.0 for a in [wk1, wk2, wk3, wk4])
        wk234_avg = (wk2 + wk3 + wk4) / 3.0
        improving = (wk1 <= -3.0 and wk234_avg > -1.0)
        drying = (wk1 >= -1.0 and wk234_avg <= -3.0)
        
        if all_below:
            summary_parts.append("the 4-week outlook shows persistently below-normal rainfall")
        elif all_above:
            summary_parts.append("the 4-week outlook shows sustained above-normal rainfall")
        elif improving:
            summary_parts.append(f"this week's rainfall is {_sig(wk1)} but the outlook improves over weeks 2-4")
        elif drying:
            summary_parts.append(f"this week's rainfall is {_sig(wk1)} but the outlook dries out over weeks 2-4")
        else:
            summary_parts.append(f"the 4-week rainfall outlook is mixed ({_sig(wk1)} this week, {_sig(wk4)} by week 4)")
        
        # Temperature/heat situation
        if forecast.get("heat_wave_warning", False):
            summary_parts.append("Heat stress is elevated with heat wave warnings in effect")
        elif forecast.get("tmax_signal") == "above_normal":
            summary_parts.append("Above-normal temperatures are expected")
        
        # Combine parts
        if len(summary_parts) == 1:
            return summary_parts[0] + "."
        elif len(summary_parts) == 2:
            return summary_parts[0] + ", " + summary_parts[1] + "."
        else:
            return summary_parts[0] + ", " + summary_parts[1] + ", and " + summary_parts[2] + "."
    
    def _generate_extended_outlook(self, forecast: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a 4-week extended outlook with plain-language interpretation."""
        wk1 = forecast.get("week1_rainfall_anomaly_mm_day", 0.0)
        wk2 = forecast.get("week2_rainfall_anomaly_mm_day", 0.0)
        wk3 = forecast.get("week3_rainfall_anomaly_mm_day", 0.0)
        wk4 = forecast.get("week4_rainfall_anomaly_mm_day", 0.0)
        seasonal_dep = forecast.get("rainfall_since_june_1_pct_departure", 0)
        
        def _label(v):
            if v >= 7.0: return "well above normal"
            if v >= 3.0: return "above normal"
            if v <= -7.0: return "well below normal"
            if v <= -3.0: return "below normal"
            return "near normal"
        
        weeks = [
            {"week": 1, "anomaly_mm_day": wk1, "label": _label(wk1)},
            {"week": 2, "anomaly_mm_day": wk2, "label": _label(wk2)},
            {"week": 3, "anomaly_mm_day": wk3, "label": _label(wk3)},
            {"week": 4, "anomaly_mm_day": wk4, "label": _label(wk4)},
        ]
        
        # Add tmax outlook if available
        tmax_wk1 = forecast.get("week1_tmax_anomaly_degC")
        tmax_wk2 = forecast.get("week2_tmax_anomaly_degC")
        tmax_wk3 = forecast.get("week3_tmax_anomaly_degC")
        tmax_wk4 = forecast.get("week4_tmax_anomaly_degC")
        if tmax_wk1 is not None:
            weeks[0]["tmax_anomaly_degC"] = tmax_wk1
        if tmax_wk2 is not None:
            weeks[1]["tmax_anomaly_degC"] = tmax_wk2
        if tmax_wk3 is not None:
            weeks[2]["tmax_anomaly_degC"] = tmax_wk3
        if tmax_wk4 is not None:
            weeks[3]["tmax_anomaly_degC"] = tmax_wk4
        
        # Build narrative
        narrative_parts = []
        
        # Week 1
        narrative_parts.append(f"This week: rainfall {_label(wk1)} ({wk1:+.0f} mm/day)")
        
        # Weeks 2-4 trajectory — collapse repeated labels for readability
        wk234_avg = (wk2 + wk3 + wk4) / 3.0
        wk234_labels = [_label(wk2), _label(wk3), _label(wk4)]
        
        def _describe_weeks_2_4(labels):
            """Collapse repeated labels into natural language."""
            if labels[0] == labels[1] == labels[2]:
                return f"{labels[0]} rainfall throughout weeks 2-4"
            elif labels[0] == labels[1]:
                return f"{labels[0]} in weeks 2-3, shifting to {labels[2]} by week 4"
            elif labels[1] == labels[2]:
                return f"{labels[0]} in week 2, then {labels[1]} through weeks 3-4"
            else:
                return f"{labels[0]} in week 2, {labels[1]} in week 3, {labels[2]} by week 4"
        
        if wk1 <= -3.0 and wk234_avg > -1.0:
            narrative_parts.append(
                f"Outlook improves — {_describe_weeks_2_4(wk234_labels)}. Some relief expected."
            )
        elif wk1 >= -1.0 and wk234_avg <= -3.0:
            narrative_parts.append(
                f"Caution — while this week is {_label(wk1)}, the outlook dries: "
                f"{_describe_weeks_2_4(wk234_labels)}."
            )
        elif all(a <= -3.0 for a in [wk1, wk2, wk3, wk4]):
            narrative_parts.append(
                "Persistent dry conditions expected across all 4 weeks."
            )
        elif all(a >= 3.0 for a in [wk1, wk2, wk3, wk4]):
            narrative_parts.append(
                "Sustained above-normal rainfall expected across all 4 weeks."
            )
        else:
            narrative_parts.append(
                f"{_describe_weeks_2_4(wk234_labels).capitalize()}."
            )
        
        # Seasonal context
        if seasonal_dep <= -30:
            narrative_parts.append(
                f"Season-to-date rainfall is {abs(seasonal_dep)}% below normal — "
                f"any above-normal rain is helpful for deficit recovery."
            )
        elif seasonal_dep >= 20:
            narrative_parts.append(
                f"Season-to-date rainfall is {seasonal_dep}% above normal — "
                f"additional heavy rain increases waterlogging risk."
            )
        
        # Temperature context
        if tmax_wk1 is not None and tmax_wk1 >= 2.0:
            narrative_parts.append(
                f"Temperatures are elevated (+{tmax_wk1:.0f}°C above normal this week)."
            )
        elif tmax_wk1 is not None and tmax_wk1 <= -2.0:
            narrative_parts.append(
                f"Temperatures are cooler than normal ({tmax_wk1:.0f}°C this week), likely due to cloud cover."
            )
        
        return {
            "weeks": weeks,
            "narrative": " ".join(narrative_parts),
        }
    
    def _generate_actions(self, scenarios: List[Dict[str, Any]], icar_data: Dict[str, Any], 
                         user_context: Dict[str, Any], forecast_data: Dict[str, Any] = None) -> Dict[str, List[str]]:
        """Generate recommended actions based on scenarios and user context."""
        actions = {
            "do_now": [],
            "prepare": [],
            "avoid": [],
            "general_guidance": []
        }
        
        user_type = user_context.get("user_type", "farmer")
        
        for scenario in scenarios:
            scenario_name = scenario["scenario"]
            
            # Get generic actions for this scenario
            generic_actions = self.action_library.get(scenario_name, {})
            
            # Get ICAR-specific actions if available
            icar_actions = {}
            if icar_data and "scenarios" in icar_data:
                icar_scenario = icar_data["scenarios"].get(scenario_name, {})
                if icar_scenario:
                    icar_actions = icar_scenario
            
            # Combine actions based on user type
            self._add_user_specific_actions(actions, generic_actions, icar_actions, user_type, scenario_name, user_context)
        
        # Baseline advisory when no risk scenarios triggered
        if not scenarios and forecast_data:
            self._add_baseline_actions(actions, forecast_data, icar_data, user_context)
        
        # Separate generic/evergreen advice into general_guidance
        self._separate_generic_advice(actions)
        
        # Remove duplicates (exact + semantic) while preserving order
        for category in actions:
            actions[category] = self._deduplicate_actions(actions[category])
        
        return actions
    
    def _add_user_specific_actions(self, actions: Dict[str, List[str]], 
                                  generic_actions: Dict[str, List[str]], 
                                  icar_actions: Dict[str, Any], 
                                  user_type: str, scenario_name: str,
                                  user_context: Dict[str, Any] = None) -> None:
        """Add user-specific actions to the action lists."""
        if user_context is None:
            user_context = {}
        
        irrigation = user_context.get("irrigation_status", "unknown")
        crop = user_context.get("crop")
        crop_stage = user_context.get("crop_stage")
        
        # Generic actions for all users (filter crop-specific items for livestock owners)
        crop_keywords = ["planting", "sowing", "crop", "fertilizer", "seed", "field operations"]
        
        def _relevant_for_user(action, utype):
            if utype == "livestock_owner":
                return not any(kw in action.lower() for kw in crop_keywords)
            return True
        
        if "do_now_all" in generic_actions:
            actions["do_now"].extend([a for a in generic_actions["do_now_all"] if _relevant_for_user(a, user_type)])
        if "prepare_all" in generic_actions:
            actions["prepare"].extend([a for a in generic_actions["prepare_all"] if _relevant_for_user(a, user_type)])
        if "avoid_all" in generic_actions:
            actions["avoid"].extend([a for a in generic_actions["avoid_all"] if _relevant_for_user(a, user_type)])
        
        # User-type specific actions
        user_type_key = user_type.replace(" ", "_")
        if f"do_now_{user_type_key}" in generic_actions:
            actions["do_now"].extend(generic_actions[f"do_now_{user_type_key}"])
        if f"prepare_{user_type_key}" in generic_actions:
            actions["prepare"].extend(generic_actions[f"prepare_{user_type_key}"])
        if f"avoid_{user_type_key}" in generic_actions:
            actions["avoid"].extend(generic_actions[f"avoid_{user_type_key}"])
        
        # Irrigation-status modulation for farmers
        if user_type == "farmer" and irrigation == "rainfed":
            if scenario_name in ["delayed_monsoon", "early_season_dry_spell", "mid_season_break", "terminal_drought"]:
                actions["do_now"].append("Rainfed field: prioritize soil moisture conservation — mulching, weeding, and dust mulch")
                actions["prepare"].append("Without irrigation backup, plan for shorter-duration or drought-tolerant varieties if re-sowing is needed")
        elif user_type == "farmer" and irrigation == "assured_irrigation":
            if scenario_name in ["delayed_monsoon", "early_season_dry_spell", "mid_season_break"]:
                actions["do_now"].append("Use irrigation strategically at critical crop stages — you have more flexibility than rainfed farmers")
        
        # ICAR-specific actions for farmers — filtered by crop if specified
        if user_type == "farmer" and icar_actions:
            if "icar_pdf_actions" in icar_actions:
                actions["do_now"].extend(icar_actions["icar_pdf_actions"])
            if "crop_actions" in icar_actions:
                crop_actions = icar_actions["crop_actions"]
                if crop:
                    # Prioritize actions mentioning the user's crop
                    crop_lower = crop.lower()
                    relevant = [a for a in crop_actions if crop_lower in a.lower()]
                    other = [a for a in crop_actions if crop_lower not in a.lower()]
                    actions["do_now"].extend(relevant)
                    actions["prepare"].extend(other)  # others go to prepare
                else:
                    actions["do_now"].extend(crop_actions)
            # Livestock actions only shown to farmers if they have livestock
            # For now, skip for pure crop farmers — livestock_owner gets these
        
        # ICAR actions for livestock owners — livestock only, no crop advice
        elif user_type == "livestock_owner" and icar_actions:
            if "livestock_actions" in icar_actions:
                actions["do_now"].extend(icar_actions["livestock_actions"])
        
        # Village official/NGO actions
        elif user_type in ["village_official", "ngo_extension_worker"]:
            if scenario_name in ["heat_stress", "delayed_monsoon", "terminal_drought", "excess_rainfall_waterlogging"]:
                actions["prepare"].extend(self._get_community_actions(scenario_name))
        
        # Health worker actions
        elif user_type == "health_worker" and scenario_name == "heat_stress":
            actions["do_now"].extend([
                "Watch for heat exhaustion and heat stroke symptoms",
                "Refer severe cases urgently to health facilities",
                "Monitor vulnerable households during alerts"
            ])
        
        # Crop-stage filtering: remove irrelevant actions
        if crop_stage:
            actions["do_now"] = self._filter_by_crop_stage(actions["do_now"], crop_stage)
            actions["prepare"] = self._filter_by_crop_stage(actions["prepare"], crop_stage)
            actions["avoid"] = self._filter_by_crop_stage(actions["avoid"], crop_stage)
    
    def _filter_by_crop_stage(self, action_list: List[str], crop_stage: str) -> List[str]:
        """Filter out actions that are irrelevant to the current crop stage.
        
        Uses keyword matching to remove actions that reference a different stage.
        Conservative: only removes if clearly irrelevant; keeps ambiguous ones.
        """
        # Keywords associated with each stage
        sowing_keywords = ["sow", "sowing", "planting", "seed bed", "nursery", "germination"]
        harvest_keywords = ["harvest", "threshing", "post-harvest", "storage of grain"]
        flowering_keywords = ["flowering", "reproductive", "grain filling", "panicle"]
        
        filtered = []
        for action in action_list:
            action_lower = action.lower()
            
            # At flowering/harvesting stage, remove sowing-specific advice
            if crop_stage in ["flowering", "flowering_reproductive", "harvesting"]:
                if any(kw in action_lower for kw in sowing_keywords) and "re-sow" not in action_lower:
                    continue
            
            # At sowing/vegetative stage, remove harvest-specific advice
            if crop_stage in ["recently_sown", "vegetative", "not_sown"]:
                if any(kw in action_lower for kw in harvest_keywords):
                    continue
            
            # At pre-sowing, remove flowering-specific advice
            if crop_stage in ["not_sown", "recently_sown"]:
                if any(kw in action_lower for kw in flowering_keywords):
                    continue
            
            filtered.append(action)
        
        return filtered
    
    def _separate_generic_advice(self, actions: Dict[str, List[str]]) -> None:
        """Move generic/evergreen advice from do_now/prepare/avoid into general_guidance.
        
        Generic advice = items that are always true regardless of the specific
        weather scenario (e.g., 'check forecasts', 'consult local ag dept',
        'care for vulnerable people').
        """
        generic_patterns = [
            "stay updated with official", "monitor weather", "monitor imd",
            "monitor forecasts", "check local kvk", "official weather forecast",
            "check on elderly", "children, pregnant women",
            "people with health conditions",
            "keep basic heat illness response",
            "store drinking water", "identify shaded or cooler",
        ]
        
        for category in ["do_now", "prepare", "avoid"]:
            remaining = []
            for action in actions[category]:
                action_lower = action.lower()
                if any(pattern in action_lower for pattern in generic_patterns):
                    actions["general_guidance"].append(action)
                else:
                    remaining.append(action)
            actions[category] = remaining
    
    def _deduplicate_actions(self, action_list: List[str]) -> List[str]:
        """Remove exact and semantic duplicates while preserving order.
        
        Uses three strategies:
        1. Exact string dedup
        2. Concept-group dedup (known duplicate themes)
        3. Word-overlap dedup (>50% shared significant words)
        
        When duplicates are found, keeps the longer (more specific) version.
        """
        if not action_list:
            return []
        
        # First pass: exact dedup
        seen_exact = set()
        unique = []
        for action in action_list:
            if action not in seen_exact:
                seen_exact.add(action)
                unique.append(action)
        
        # Concept groups: actions matching the same group are duplicates
        concept_groups = [
            ["conserve water", "use water efficiently", "water judiciously", "essential needs only"],
            ["applying fertilizer before", "fertilizer to dry soil", "fertilizer without moisture"],
            ["re-sowing too early", "re-sowing if plant stand", "consider re-sowing"],
            ["non-essential water", "waste water on non-essential"],
            ["prepare contingency plans for water", "review water conservation"],
            ["short-duration crop", "short-duration rice", "shorter-duration"],
            ["delay fertilizer application", "delay fertilizer"],
        ]
        
        def get_concept(text):
            text_lower = text.lower()
            for i, group in enumerate(concept_groups):
                if any(phrase in text_lower for phrase in group):
                    return i
            return None
        
        # Second pass: concept dedup — keep longest per concept
        result = []
        seen_concepts = {}  # concept_id -> index in result
        for action in unique:
            concept = get_concept(action)
            if concept is not None and concept in seen_concepts:
                idx = seen_concepts[concept]
                if len(action) > len(result[idx]):
                    result[idx] = action
            elif concept is not None:
                seen_concepts[concept] = len(result)
                result.append(action)
            else:
                result.append(action)
        
        # Third pass: word-overlap dedup for remaining
        stop_words = {"the", "a", "an", "is", "are", "for", "to", "of", "and", "or",
                      "in", "on", "at", "with", "from", "by", "if", "it", "be", "as",
                      "that", "this", "not", "do", "use", "where", "when", "only"}
        
        def significant_words(text):
            return set(w for w in text.lower().split() if w not in stop_words and len(w) > 2)
        
        final = []
        for action in result:
            words_i = significant_words(action)
            is_duplicate = False
            for j, kept in enumerate(final):
                words_j = significant_words(kept)
                if not words_i or not words_j:
                    continue
                overlap = len(words_i & words_j)
                smaller = min(len(words_i), len(words_j))
                if smaller > 0 and overlap / smaller >= 0.5:
                    if len(action) > len(kept):
                        final[j] = action
                    is_duplicate = True
                    break
            if not is_duplicate:
                final.append(action)
        
        return final
    
    def _get_community_actions(self, scenario_name: str) -> List[str]:
        """Get community-level actions for officials and NGOs."""
        community_actions = {
            "heat_stress": [
                "Identify vulnerable households in the community",
                "Arrange drinking water points in public spaces",
                "Identify shaded community spaces for rest",
                "Coordinate public messaging about heat safety",
                "Check school and outdoor labor timing with local authorities"
            ],
            "delayed_monsoon": [
                "Review drinking water sources in the village",
                "Check pumps, ponds, tanks, and local water storage",
                "Identify priority water uses for the community",
                "Coordinate fodder planning with livestock owners",
                "Consider community water conservation works if conditions persist"
            ],
            "terminal_drought": [
                "Review and secure drinking water sources",
                "Coordinate emergency water supply if needed",
                "Organize community fodder banks for livestock",
                "Identify most vulnerable households for support",
                "Coordinate with district authorities for drought response"
            ],
            "excess_rainfall_waterlogging": [
                "Identify flood-prone areas in the community",
                "Protect water sources from contamination",
                "Coordinate warnings and evacuation support if needed",
                "Organize community drainage clearing efforts",
                "Monitor for waterborne disease outbreaks"
            ]
        }
        
        return community_actions.get(scenario_name, [])
    
    def _add_baseline_actions(self, actions: Dict[str, List[str]], 
                              forecast: Dict[str, Any], icar_data: Dict[str, Any],
                              user_context: Dict[str, Any]) -> None:
        """Generate planning guidance when no risk scenario is active.
        
        Provides opportunity-based and preparedness advice based on the
        4-week outlook trajectory and seasonal context.
        """
        wk1 = forecast.get("week1_rainfall_anomaly_mm_day", 0.0)
        wk2 = forecast.get("week2_rainfall_anomaly_mm_day", 0.0)
        wk3 = forecast.get("week3_rainfall_anomaly_mm_day", 0.0)
        wk4 = forecast.get("week4_rainfall_anomaly_mm_day", 0.0)
        seasonal_dep = forecast.get("rainfall_since_june_1_pct_departure", 0)
        user_type = user_context.get("user_type", "farmer")
        
        # Opportunity: above-normal rain this week — good for sowing/field ops
        if wk1 >= 3.0 and user_type in ["farmer", "livestock_owner"]:
            actions["do_now"].append("Good moisture conditions expected this week — favorable for sowing or field operations")
            if seasonal_dep <= -20:
                actions["do_now"].append("Take advantage of rainfall for deficit recovery — conserve soil moisture where possible")
        
        # Near-normal conditions — routine advice
        if -3.0 < wk1 < 3.0 and user_type in ["farmer", "livestock_owner"]:
            actions["do_now"].append("Conditions are near normal — continue routine crop management and monitoring")
        
        # Preparedness: drying trend ahead
        wk234_avg = (wk2 + wk3 + wk4) / 3.0
        if wk234_avg <= -3.0:
            if user_type in ["farmer", "livestock_owner"]:
                actions["prepare"].append("Rainfall outlook dries out over weeks 2-4 — conserve soil moisture and plan water use carefully")
                actions["prepare"].append("Check irrigation sources and repair water-harvesting structures")
            elif user_type in ["village_official", "ngo_extension_worker"]:
                actions["prepare"].append("Rainfall outlook dries out over weeks 2-4 — review community water sources")
        
        # Preparedness: wetting trend ahead
        if wk234_avg >= 3.0:
            if user_type in ["farmer", "livestock_owner"]:
                actions["prepare"].append("Above-normal rainfall expected in coming weeks — ensure field drainage is clear")
                actions["prepare"].append("Plan pesticide/fungicide applications around expected wet spells")
        
        # Seasonal deficit context
        if seasonal_dep <= -30 and user_type in ["farmer", "livestock_owner"]:
            actions["prepare"].append(f"Season-to-date rainfall is {abs(seasonal_dep)}% below normal — prioritize moisture conservation")
        
        # General monitoring
        actions["do_now"].append("Monitor IMD forecasts and local KVK advisories for updates")
    
    def _load_action_library(self) -> Dict[str, Dict[str, List[str]]]:
        """Load the action library for different scenarios."""
        return {
            "heat_stress": {
                "do_now_all": [
                    "Avoid heavy outdoor work during the hottest part of the day",
                    "Drink water frequently; use ORS where appropriate",
                    "Rest in shade or cooler spaces",
                    "Check on elderly people, children, pregnant women, and people with health conditions"
                ],
                "prepare_all": [
                    "Store drinking water",
                    "Identify shaded or cooler community spaces",
                    "Coordinate work shifts for early morning or evening",
                    "Keep basic heat illness response information available"
                ],
                "avoid_all": [
                    "Long outdoor work without rest breaks",
                    "Leaving children, elderly people, or animals in enclosed hot spaces",
                    "Unnecessary livestock transport during peak heat"
                ],
                "do_now_livestock_owner": [
                    "Provide shade and continuous drinking water for livestock",
                    "Avoid grazing or transport during peak heat",
                    "Watch for panting, drooling, weakness, or reduced feed intake in animals"
                ],
                "do_now_outdoor_worker": [
                    "Shift heavy work to early morning or evening",
                    "Use work-rest cycles during heat alerts",
                    "Ensure drinking water and ORS availability at worksite"
                ]
            },
            "delayed_monsoon": {
                "do_now_all": [
                    "Conserve water and use it judiciously",
                    "Stay updated with official weather forecasts"
                ],
                "prepare_all": [
                    "Prepare for potential changes in planting schedules",
                    "Review water storage and conservation options"
                ],
                "avoid_all": [
                    "Panic or make drastic agricultural decisions without official guidance",
                    "Waste water on non-essential activities"
                ],
                "do_now_farmer": [
                    "Do not rush sowing without adequate soil moisture",
                    "Preserve seed for the right sowing window",
                    "Check local KVK or agriculture officer guidance"
                ],
                "prepare_farmer": [
                    "Prepare short-duration crop or variety options",
                    "Repair field bunds and water-harvesting structures",
                    "Consider lower-water alternatives where locally suitable"
                ],
                "avoid_farmer": [
                    "Sowing long-duration crops if the sowing window is already delayed",
                    "Applying fertilizer before adequate moisture is available",
                    "Repeated dry sowing without rainfall support"
                ]
            },
            "early_season_dry_spell": {
                "do_now_all": [
                    "Use water efficiently for essential needs only",
                    "Monitor weather forecasts regularly"
                ],
                "prepare_all": [
                    "Prepare contingency plans for water scarcity",
                    "Review water conservation measures"
                ],
                "avoid_all": [
                    "Non-essential water use",
                    "Ignoring early signs of moisture stress"
                ],
                "do_now_farmer": [
                    "Assess germination and plant stand",
                    "Use protective irrigation if available",
                    "Delay fertilizer application until rainfall or irrigation is available"
                ],
                "prepare_farmer": [
                    "Keep contingency seed ready",
                    "Plan for re-sowing only if crop stand has failed and the sowing window remains open",
                    "Conserve soil moisture through weeding, mulching, or interculture where appropriate"
                ],
                "avoid_farmer": [
                    "Applying fertilizer to dry soil",
                    "Re-sowing too early without rainfall support"
                ]
            },
            "mid_season_break": {
                "do_now_all": [
                    "Prioritize water for most critical needs",
                    "Monitor crop and livestock conditions closely"
                ],
                "prepare_all": [
                    "Plan for potential water rationing",
                    "Review alternative water sources"
                ],
                "avoid_all": [
                    "Non-essential water consumption",
                    "Ignoring signs of stress in crops and livestock"
                ],
                "do_now_farmer": [
                    "Prioritize protective irrigation during critical crop stages",
                    "Remove weeds to reduce moisture competition",
                    "Use soil moisture conservation practices"
                ],
                "prepare_farmer": [
                    "Adjust fertilizer timing",
                    "Prepare fodder alternatives",
                    "Coordinate community water use if dry conditions continue"
                ],
                "avoid_farmer": [
                    "Nonessential irrigation for low-priority fields",
                    "Fertilizer or pesticide application during severe moisture stress unless locally advised"
                ]
            },
            "terminal_drought": {
                "do_now_all": [
                    "Prioritize drinking water for all",
                    "Conserve water for essential uses only"
                ],
                "prepare_all": [
                    "Prepare for extended water scarcity",
                    "Review emergency water sources"
                ],
                "avoid_all": [
                    "Non-essential water use",
                    "Wasting water on lost causes"
                ],
                "do_now_farmer": [
                    "Prioritize water for crops at critical reproductive stages",
                    "Avoid spending scarce irrigation on failed or low-priority crops",
                    "Prepare for fodder shortage"
                ],
                "prepare_farmer": [
                    "Plan early harvest where locally advised",
                    "Store crop residues for fodder",
                    "Coordinate village-level livestock water and fodder planning"
                ],
                "avoid_farmer": [
                    "Late fertilizer application without moisture",
                    "Replanting when the viable crop window has passed"
                ]
            },
            "excess_rainfall_waterlogging": {
                "do_now_all": [
                    "Avoid unnecessary travel in flooded areas",
                    "Protect important documents and valuables"
                ],
                "prepare_all": [
                    "Identify higher ground for emergency shelter",
                    "Prepare emergency supplies"
                ],
                "avoid_all": [
                    "Entering flooded areas unnecessarily",
                    "Contaminated water consumption"
                ],
                "do_now_farmer": [
                    "Clear drainage channels",
                    "Avoid field operations during heavy rain",
                    "Move livestock away from flood-prone areas"
                ],
                "prepare_farmer": [
                    "Identify higher ground for livestock and equipment",
                    "Watch for pest and disease outbreaks after rainfall",
                    "Repair bunds after water recedes"
                ],
                "avoid_farmer": [
                    "Entering flooded fields unnecessarily",
                    "Applying fertilizer before heavy rainfall",
                    "Allowing livestock to drink contaminated stagnant water"
                ]
            }
        }
