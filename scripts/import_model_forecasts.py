#!/usr/bin/env python3
"""
Import model-derived forecasts into district_forecasts.json.

Bridges the india_forecasts model pipeline into the advisor. It OVERWRITES the
forecast fields with model output while PRESERVING the IMD-derived observed fields
(rainfall departures, monsoon onset status, official heat/heavy-rain warnings) that
the models cannot provide -- an augment, not a replace.

Inputs (produced next door in enso_india/india_forecasts, paths configurable):
  * Subseasonal weekly : plots/s2s_region_weekly.csv   (forecast_region_s2s.py)
        per district/week: precip_anom_mm_day, t2m_anom_degC, n_models, init_date
  * Seasonal monthly   : plots/forecast_<slug>.csv      (forecast_region.py)
        per district/lead: variable(t/p), category, p_below/p_near/p_above, ...

Field mapping (advisor JSON <- model):
  weekN_rainfall_anomaly_mm_day   <- S2S multi-model mean precip anomaly
  weekN_tmax_anomaly_degC         <- S2S multi-model mean t2m anomaly
  weekN_rainfall_signal, week3_4  <- derived from the weekly precip anomaly
  tmax_signal                     <- derived from week-1 t2m anomaly
  seasonal_monsoon_context        <- seasonal precip terciles over the monsoon leads
  forecast_date                   <- S2S init date
  forecast_source                 <- provenance string
PRESERVED (IMD): rainfall_since_june_1/7d/14d_pct_departure, monsoon_onset_status,
  heat_wave_warning, heavy_rain_warning, humidity_heat_index_signal.

Usage (run from the advisor project root):
    python scripts/import_model_forecasts.py
    python scripts/import_model_forecasts.py --s2s /path/s2s_region_weekly.csv --seasonal-dir /path/plots
    python scripts/import_model_forecasts.py --no-backup
"""

import os
import re
import csv
import json
import shutil
import argparse
from pathlib import Path
from datetime import datetime

ADVISOR_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = ADVISOR_ROOT / "data" / "district_forecasts.json"
# the forecast pipeline is vendored into the repo at gram-climate-advisor/india_forecasts/
DEFAULT_PLOTS = ADVISOR_ROOT / "india_forecasts" / "plots"

RAIN_ABOVE, RAIN_BELOW = 3.0, -3.0     # mm/day thresholds (match extract_rainfall_anomaly.py)
TMAX_ABOVE, TMAX_BELOW = 1.5, -1.5     # degC thresholds (match app.py _temp_cell_color)
SEASONAL_TERCILE_MARGIN = 0.10         # net (p_above - p_below) needed to call a side
NOTE_MARKER = " [forecast fields: model import]"


# --------------------------------------------------------------------------
# derivations
# --------------------------------------------------------------------------
def rain_signal(anom):
    if anom is None or anom == "":
        return "near_normal"
    a = float(anom)
    if a >= RAIN_ABOVE:
        return "above_normal"
    if a <= RAIN_BELOW:
        return "below_normal"
    return "near_normal"


def tmax_signal(anom):
    if anom is None or anom == "":
        return "near_normal"
    a = float(anom)
    if a >= TMAX_ABOVE:
        return "above_normal"
    if a <= TMAX_BELOW:
        return "below_normal"
    return "near_normal"


def _norm(s):
    """alnum-lowercase; collapses 'Uttar Pradesh' and 'UttarPradesh' to the same key."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# S2S weekly
# --------------------------------------------------------------------------
def load_s2s(path):
    """-> {(state_lc, district_lc): {'init': 'YYYYMMDD',
                                     'by_model': {model: {week: {'precip','t2m'}}}}}
    Reads the long-format CSV (one row per district/week/model, model incl 'MME')."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["state"].strip().lower(), r["district"].strip().lower())
            d = out.setdefault(key, {"init": r.get("init_date", ""), "by_model": {}})
            model = r.get("model") or "MME"
            d["by_model"].setdefault(model, {})[int(r["week"])] = {
                "precip": _f(r.get("precip_anom_mm_day")),
                "t2m": _f(r.get("t2m_anom_degC")),
            }
    return out


MODEL_LABELS = {
    "MME": "Multi-model mean",
    "GEFS": "GEFS (NOAA 35-day)",
    "CFSv2": "CFSv2 (NOAA)",
    "EC46": "EC46 (ECMWF 46-day)",
}


def load_probs(path):
    """-> {(state_lc, district_lc): {'source','n_members','init','weeks':[{week,p_wetter,...}]}}.
    Reads s2s_region_probs.csv (weekly threshold-exceedance odds from the ensemble)."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["state"].strip().lower(), r["district"].strip().lower())
            d = out.setdefault(key, {"source": "GEFS ensemble", "n_members": None,
                                     "init": r.get("init_date", ""), "weeks": []})
            d["weeks"].append({
                "week": int(r["week"]),
                "p_wetter": _f(r.get("p_wetter")), "p_near": _f(r.get("p_near")),
                "p_drier": _f(r.get("p_drier")), "p_heavy": _f(r.get("p_heavy")),
                "p_dryspell": _f(r.get("p_dryspell")), "p_hot": _f(r.get("p_hot")),
            })
            nm = _f(r.get("n_members"))
            if nm is not None:
                d["n_members"] = int(nm)
    for d in out.values():
        d["weeks"].sort(key=lambda x: x["week"])
    return out


def _weeks_list(wk_by_week):
    """{week: {'precip','t2m'}} -> [{'week','rainfall_mm_day','tmax_degC'}] sorted by week."""
    return [{"week": w,
             "rainfall_mm_day": wk_by_week[w].get("precip"),
             "tmax_degC": wk_by_week[w].get("t2m")}
            for w in sorted(wk_by_week)]


# --------------------------------------------------------------------------
# Seasonal terciles -> monsoon context
# --------------------------------------------------------------------------
def build_seasonal_index(seasonal_dir):
    """Map (norm_state, norm_district) -> csv path by reading each forecast_*.csv's
    'region' column ('<District> district, <State>'). Robust to slug/state spelling
    quirks (GADM stores e.g. 'UttarPradesh')."""
    index = {}
    for path in sorted(Path(seasonal_dir).glob("forecast_*.csv")):
        if path.name == "s2s_region_weekly.csv":
            continue
        try:
            with open(path, newline="") as fh:
                row = next(csv.DictReader(fh), None)
        except OSError:
            continue
        region = (row or {}).get("region", "")
        if " district," not in region:
            continue  # state-level file, not a district
        dpart, _, spart = region.partition(" district,")
        index[(_norm(spart), _norm(dpart))] = path
    return index


def seasonal_context(seasonal_index, state, district, monsoon_leads=(0, 1, 2, 3)):
    """Classify the monsoon-season precip signal from the seasonal tercile CSV by
    averaging p_above/p_below across the monsoon leads and models. Returns one of
    'below_normal_risk' / 'normal' / 'above_normal', or None if no CSV."""
    path = seasonal_index.get((_norm(state), _norm(district)))
    if path is None or not path.exists():
        return None, None
    above, below, n = [], [], 0
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("variable") != "p":
                continue
            try:
                lead = int(r["lead"])
            except (KeyError, ValueError):
                continue
            if lead not in monsoon_leads:
                continue
            pa, pb = _f(r.get("p_above")), _f(r.get("p_below"))
            if pa is None or pb is None:
                continue
            above.append(pa)
            below.append(pb)
            n += 1
    if not above:
        return None, None
    net = sum(above) / len(above) - sum(below) / len(below)
    if net >= SEASONAL_TERCILE_MARGIN:
        ctx = "above_normal"
    elif net <= -SEASONAL_TERCILE_MARGIN:
        ctx = "below_normal_risk"
    else:
        ctx = "normal"
    return ctx, {"net": round(net, 3), "leads": n}


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------
def _set_note(existing, add):
    base = (existing or "").split(NOTE_MARKER)[0].rstrip()
    return f"{base}{NOTE_MARKER}: {add}"


def merge(forecasts, s2s, seasonal_index):
    updated, skipped = [], []
    for fc in forecasts:
        key = (fc.get("state", "").strip().lower(), fc.get("district", "").strip().lower())
        if key not in s2s:
            skipped.append(f"{fc.get('district')}, {fc.get('state')}")
            continue
        by_model = s2s[key]["by_model"]
        init = s2s[key]["init"]
        mme = by_model.get("MME", {})

        # capture the IMD baseline from the current top-level fields BEFORE overwriting.
        # Preserve it across re-runs (once top-level is MME we must not recapture it).
        prior = fc.get("forecast_variants") or []
        imd_variant = next((v for v in prior if v.get("key") == "IMD"), None)
        if imd_variant is None:
            base_note = (fc.get("imd_source_notes") or "").split(NOTE_MARKER)[0].rstrip()
            imd_variant = {
                "key": "IMD", "label": "Official IMD guidance",
                "source": base_note or "IMD forecast products",
                "weeks": [{"week": w,
                           "rainfall_mm_day": fc.get(f"week{w}_rainfall_anomaly_mm_day"),
                           "tmax_degC": fc.get(f"week{w}_tmax_anomaly_degC")}
                          for w in (1, 2, 3, 4)],
            }

        # overwrite the active (rule-engine) fields with the multi-model mean
        for w in (1, 2, 3, 4):
            fc[f"week{w}_rainfall_anomaly_mm_day"] = mme.get(w, {}).get("precip")
            fc[f"week{w}_tmax_anomaly_degC"] = mme.get(w, {}).get("t2m")
        fc["week1_rainfall_signal"] = rain_signal(mme.get(1, {}).get("precip"))
        fc["week2_rainfall_signal"] = rain_signal(mme.get(2, {}).get("precip"))
        w3, w4 = mme.get(3, {}).get("precip"), mme.get(4, {}).get("precip")
        vals34 = [v for v in (w3, w4) if v is not None]
        fc["week3_4_rainfall_signal"] = rain_signal(sum(vals34) / len(vals34) if vals34 else None)
        fc["tmax_signal"] = tmax_signal(mme.get(1, {}).get("t2m"))

        # seasonal monsoon context (terciles); leave existing value if no seasonal CSV
        ctx, meta = seasonal_context(seasonal_index, fc.get("state"), fc.get("district"))
        seas_note = ""
        if ctx:
            fc["seasonal_monsoon_context"] = ctx
            seas_note = f"; seasonal SEAS5+SFS -> {ctx} (net {meta['net']:+.2f})"

        if init:
            try:
                fc["forecast_date"] = datetime.strptime(init, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

        member_models = sorted(m for m in by_model if m != "MME")
        used = ",".join(member_models) if member_models else "models"
        fc["forecast_source"] = (f"S2S multi-model mean ({used}) "
                                 f"init {fc.get('forecast_date', init)}{seas_note}")
        fc["imd_source_notes"] = _set_note(fc.get("imd_source_notes"), fc["forecast_source"])

        # selectable variants for the Source Data tab: IMD, MME, then each model
        variants = [imd_variant, {
            "key": "MME",
            "label": f"Multi-model mean ({','.join(member_models)})" if member_models else "Multi-model mean",
            "source": fc["forecast_source"],
            "weeks": _weeks_list(mme),
        }]
        for m in member_models:
            variants.append({"key": m, "label": MODEL_LABELS.get(m, m), "weeks": _weeks_list(by_model[m])})
        fc["forecast_variants"] = variants

        updated.append(f"{fc.get('district')}, {fc.get('state')}")
    return updated, skipped


def main():
    ap = argparse.ArgumentParser(description="Import india_forecasts model output into district_forecasts.json.")
    ap.add_argument("--s2s", default=str(DEFAULT_PLOTS / "s2s_region_weekly.csv"),
                    help="S2S weekly CSV from forecast_region_s2s.py.")
    ap.add_argument("--seasonal-dir", default=str(DEFAULT_PLOTS),
                    help="Directory holding forecast_<slug>.csv seasonal outputs.")
    ap.add_argument("--probs", default=str(DEFAULT_PLOTS / "s2s_region_probs.csv"),
                    help="Weekly threshold-probability CSV from forecast_region_s2s.py --probs (optional).")
    ap.add_argument("--json", default=str(DEFAULT_JSON), help="district_forecasts.json to update in place.")
    ap.add_argument("--no-backup", action="store_true", help="Do not write a .bak of the JSON first.")
    args = ap.parse_args()

    if not os.path.exists(args.s2s):
        raise SystemExit(f"S2S CSV not found: {args.s2s}\n"
                         f"  Generate it first:\n"
                         f"    cd .../india_forecasts && python forecast_region_s2s.py")
    with open(args.json, encoding="utf-8") as fh:
        forecasts = json.load(fh)

    s2s = load_s2s(args.s2s)
    print(f"S2S districts: {len(s2s)}   JSON districts: {len(forecasts)}")

    if not args.no_backup:
        shutil.copyfile(args.json, args.json + ".bak")
        print(f"backup -> {args.json}.bak")

    seasonal_index = build_seasonal_index(args.seasonal_dir)
    print(f"seasonal CSVs indexed: {len(seasonal_index)}")
    updated, skipped = merge(forecasts, s2s, seasonal_index)

    # attach weekly threshold probabilities (additive; optional)
    if os.path.exists(args.probs):
        probs = load_probs(args.probs)
        n_prob = 0
        for fc in forecasts:
            key = (fc.get("state", "").strip().lower(), fc.get("district", "").strip().lower())
            if key in probs:
                fc["weekly_probabilities"] = probs[key]
                n_prob += 1
        print(f"weekly_probabilities attached to {n_prob} district(s)")
    else:
        print(f"(no probabilities CSV at {args.probs}; skipping weekly odds)")

    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(forecasts, fh, indent=2)

    print(f"\n[OK] updated {len(updated)} district(s): {', '.join(updated)}")
    if skipped:
        print(f"[--] no model data for {len(skipped)} (left unchanged): {', '.join(skipped)}")
    print(f"[->] wrote {args.json}")


if __name__ == "__main__":
    main()
