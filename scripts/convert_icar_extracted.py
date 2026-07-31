#!/usr/bin/env python3
"""Convert icar_extracted_v2.json into the app-compatible icar_contingency_actions.json.

The extractor produces verbatim records with provenance (page, column, crop,
farming_situation, placeholder/ditto flags).  The Streamlit app's
AdvisoryGenerator expects:

    {
      "state": ..., "district": ...,
      "source": "ICAR-CRIDA ...",
      "scenarios": {
        "delayed_monsoon": {
          "crop_actions": [
            {"action": "...", "crop": "Rice", "farming_situation": "Lowland"},
            ...
          ],
          "livestock_actions": [{"action": "...", ...}, ...],
          "local_override_notes": []
        },
        ...
      }
    }

This script bridges the two:

  * Drops placeholder records (``placeholder: true``).
  * Splits records into ``crop_actions`` vs ``livestock_actions`` by keyword.
  * Stores crop/farming_situation as structured metadata (not prefixed onto
    the action text) so the UI can display them separately.
  * Carries ``major_crops`` (deduplicated crop names) for the UI.

Usage:
    python scripts/convert_icar_extracted.py
"""

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "data" / "icar_extracted_v2.json"
_DST = _ROOT / "data" / "icar_contingency_actions.json"

# Keywords that indicate livestock/poultry/fishery advice rather than crop advice.
_LIVESTOCK_KEYWORDS = re.compile(
    r"\b(cattle|cow|buffalo|poultry|goat|sheep|livestock|fodder|"
    r"feed ingredient|birds|fish|pig|camel|donkey|animal|"
    r"grazing|breed|vaccin|deworm|shed|piggery|fishery|"
    r"duck|hen|chick|hatch|milch|calving|lamb|kid\b|ewe)\b",
    re.IGNORECASE,
)

# Scenario keys the app knows about.
_SCENARIOS = [
    "delayed_monsoon",
    "early_season_dry_spell",
    "mid_season_break",
    "terminal_drought",
    "excess_rainfall_waterlogging",
]


def _is_livestock(action: str) -> bool:
    return bool(_LIVESTOCK_KEYWORDS.search(action))


def convert() -> list[dict]:
    with open(_SRC, encoding="utf-8") as f:
        extracted = json.load(f)

    output: list[dict] = []
    for district in extracted:
        state = district["state"]
        district_name = district["district"]
        scenarios_out: dict[str, dict[str, list]] = {}
        major_crops: set[str] = set()

        for scen_key in _SCENARIOS:
            records = district.get("scenarios", {}).get(scen_key, [])
            crop_actions: list[dict] = []
            livestock_actions: list[dict] = []
            seen: set[str] = set()

            for rec in records:
                if rec.get("placeholder"):
                    continue
                action = rec["action"]
                crop = rec.get("crop", "")
                farming = rec.get("farming_situation", "")

                if crop:
                    major_crops.add(crop.split("-")[0].strip())

                # Deduplicate within the scenario on (action, crop, farming).
                key = (action.lower(), crop.lower(), farming.lower())
                if key in seen:
                    continue
                seen.add(key)

                entry = {"action": action}
                if crop:
                    entry["crop"] = crop
                if farming:
                    entry["farming_situation"] = farming

                if _is_livestock(action):
                    livestock_actions.append(entry)
                else:
                    crop_actions.append(entry)

            scenarios_out[scen_key] = {
                "crop_actions": crop_actions,
                "livestock_actions": livestock_actions,
                "local_override_notes": [],
            }

        output.append({
            "state": state,
            "district": district_name,
            "source": "ICAR-CRIDA District Agriculture Contingency Plan (verbatim extraction)",
            "source_url": f"https://www.icar-crida.res.in/Crop_Contingency_Plan.html",
            "local_sources": [],
            "major_crops": sorted(major_crops)[:10],
            "scenarios": scenarios_out,
            "source_pdf": district.get("source_pdf", ""),
            "pages": district.get("pages", 0),
        })

    return output


def main() -> None:
    if not _SRC.exists():
        raise SystemExit(f"Source not found: {_SRC}")
    output = convert()
    with open(_DST, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(output)} districts -> {_DST}")

    # Quick stats
    total_crop = total_livestock = 0
    for d in output:
        for s in d["scenarios"].values():
            total_crop += len(s["crop_actions"])
            total_livestock += len(s["livestock_actions"])
    print(f"  crop_actions: {total_crop}")
    print(f"  livestock_actions: {total_livestock}")


if __name__ == "__main__":
    main()
