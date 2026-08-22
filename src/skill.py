"""
Forecast skill -> confidence, measured rather than assumed.

data/forecast_skill.json (built by india_forecasts/backtest/build_skill.py) holds, per
variable x lead-week and per climate zone, how well the multi-model forecast the app ships
has verified against IMD observations in the district backtest: anomaly correlation (ACC),
a High/Medium/Low tier derived from it, and how often each displayed category ("drier than
normal", "warmer than normal", ...) actually verified when it was forecast.

The rule engine uses week_tier() to label a scenario's confidence by the skill of the
forecast weeks the classification rests on; the app uses it for the per-week outlook
confidence and the "how reliable is this" panel. Everything degrades gracefully: with no
skill file every helper returns None and callers fall back to their previous behaviour.
"""

import csv
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(_ROOT, "data", "forecast_skill.json")
_COORDS_PATH = os.path.join(_ROOT, "data", "district_coordinates.csv")

TIERS = ("Low", "Medium", "High")
_RANK = {t: i for i, t in enumerate(TIERS)}

VARIABLE_LABEL = {"precip": "rainfall", "t2m": "temperature"}
CATEGORY_LABEL = {
    ("precip", "below"): "drier than normal",
    ("precip", "above"): "wetter than normal",
    ("precip", "heavy"): "much wetter (heavy rain)",
    ("precip", "near"): "near normal",
    ("t2m", "above"): "warmer than normal",
    ("t2m", "below"): "cooler than normal",
    ("t2m", "near"): "near normal",
}

_cache = {}


def load_skill(path=SKILL_PATH):
    """Parsed forecast_skill.json (cached on mtime), or None if absent/unreadable."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    _cache[path] = (mtime, data)
    return data


def _norm(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def district_zone(state, district):
    """Climate zone ('South India', ...) of a district from district_coordinates.csv, or None."""
    idx = _cache.get("_zones")
    if idx is None:
        idx = {}
        try:
            with open(_COORDS_PATH, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    idx[(_norm(r.get("state")), _norm(r.get("district")))] = r.get("region") or None
        except OSError:
            pass
        _cache["_zones"] = idx
    return idx.get((_norm(state), _norm(district)))


def week_skill(skill, variable, week, zone=None):
    """Skill record for (variable, week): the zone's cell when the backtest has enough
    samples there, else the national one. Adds 'scope' saying which was used."""
    if not skill:
        return None
    wk = str(int(week))
    if zone:
        rec = skill.get("zones", {}).get(zone, {}).get(variable, {}).get(wk)
        if rec:
            return dict(rec, scope=zone)
    rec = skill.get("national", {}).get(variable, {}).get(wk)
    return dict(rec, scope="India") if rec else None


def week_tier(skill, variable, week, zone=None):
    """'High' / 'Medium' / 'Low' for a forecast week, or None without a skill table."""
    rec = week_skill(skill, variable, week, zone)
    return rec.get("tier") if rec else None


def weakest(tiers):
    """The lowest tier among those given (None entries ignored); None if nothing to compare."""
    known = [t for t in tiers if t in _RANK]
    return min(known, key=_RANK.get) if known else None


def period(skill):
    """'2021-2025' style period string from the skill file's metadata."""
    p = (skill or {}).get("_meta", {}).get("period", "")
    return p.split(",")[0].strip() if p else ""


def describe(skill, variable, week, zone=None, category=None):
    """One plain-language line on why a forecast week earns its tier, e.g.
    "Week 3 rainfall: Low confidence (skill 0.27, South India, 2021-2025); 'drier than
    normal' calls verified 66% of the time (chance 24%)"."""
    rec = week_skill(skill, variable, week, zone)
    if not rec:
        return None
    label = VARIABLE_LABEL.get(variable, variable)
    s = f"Week {int(week)} {label}: {rec.get('tier', '?')} confidence"
    bits = []
    if rec.get("acc") is not None:
        bits.append(f"skill {rec['acc']:.2f}")
    bits.append(rec.get("scope", "India"))
    if period(skill):
        bits.append(period(skill))
    s += f" ({', '.join(bits)})"
    cat = (rec.get("categories") or {}).get(category) if category else None
    if cat and cat.get("hit_rate") is not None:
        s += (f"; '{CATEGORY_LABEL.get((variable, category), category)}' calls verified "
              f"{cat['hit_rate']:.0%} of the time (chance {cat['base_rate']:.0%})")
    return s


def category_hit(skill, variable, week, category, zone=None):
    """(hit_rate, base_rate) for a displayed category at a lead week, or None."""
    rec = week_skill(skill, variable, week, zone)
    cat = (rec or {}).get("categories", {}).get(category)
    if not cat or cat.get("hit_rate") is None:
        return None
    return cat["hit_rate"], cat["base_rate"]
