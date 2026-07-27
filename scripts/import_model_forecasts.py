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
            d = out.setdefault(key, {"init": r.get("init_date", ""), "by_model": {},
                                     "state": r.get("state", ""), "district": r.get("district", "")})
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
            d = out.setdefault(key, {"n_members": None, "models": r.get("models", ""),
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
        d["source"] = f"{d['models']} ensemble" if d.get("models") else "ensemble"
    return out


def _int(x, default=0):
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return default


def load_observed(path):
    """-> {(state_lc, district_lc): {observed fields}} from observed_departures.csv."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["state"].strip().lower(), r["district"].strip().lower())
            clip = lambda v: max(-100, min(300, _int(v)))   # keep departures display-sane
            out[key] = {
                "rainfall_since_june_1_pct_departure": clip(r.get("rainfall_since_june_1_pct_departure")),
                "rainfall_last_7_days_pct_departure": clip(r.get("rainfall_last_7_days_pct_departure")),
                "rainfall_last_14_days_pct_departure": clip(r.get("rainfall_last_14_days_pct_departure")),
                "monsoon_onset_status": r.get("monsoon_onset_status") or "normal",
                "obs_asof": r.get("obs_asof", ""),
            }
    return out


def _default_record(state, district):
    """Baseline record for a district not yet in district_forecasts.json (mirrors
    src/utils.get_default_forecast). merge() then fills the model forecast fields;
    observed fields stay at these neutral defaults until an observed producer sets them."""
    return {
        "state": state, "district": district, "forecast_date": "",
        "rainfall_since_june_1_pct_departure": 0, "rainfall_last_7_days_pct_departure": 0,
        "rainfall_last_14_days_pct_departure": 0, "monsoon_onset_status": "normal",
        "week1_rainfall_signal": "near_normal", "week2_rainfall_signal": "near_normal",
        "week3_4_rainfall_signal": "near_normal", "seasonal_monsoon_context": "normal",
        "tmax_signal": "near_normal", "tmin_signal": "near_normal",
        "heat_wave_warning": False, "heavy_rain_warning": False,
        "humidity_heat_index_signal": "normal", "imd_source_notes": "",
    }


def _weeks_list(wk_by_week):
    """{week: {'precip','t2m'}} -> [{'week','rainfall_mm_day','tmax_degC'}] sorted by week."""
    return [{"week": w,
             "rainfall_mm_day": wk_by_week[w].get("precip"),
             "tmax_degC": wk_by_week[w].get("t2m")}
            for w in sorted(wk_by_week)]


# --------------------------------------------------------------------------
# Seasonal terciles -> monsoon context
# --------------------------------------------------------------------------
def load_seasonal(path):
    """-> {(state_lc, district_lc): [(lead, p_above, p_below)]} for precip, from the
    combined seasonal CSV written by forecast_region.py --districts."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("variable") != "p":
                continue
            key = (r["state"].strip().lower(), r["district"].strip().lower())
            try:
                lead = int(r["lead"])
            except (KeyError, ValueError):
                continue
            pa, pb = _f(r.get("p_above")), _f(r.get("p_below"))
            if pa is None or pb is None:
                continue
            out.setdefault(key, []).append((lead, pa, pb))
    return out


def seasonal_context(seasonal, state, district, monsoon_leads=(0, 1, 2, 3)):
    """Classify the monsoon-season precip signal by averaging the tercile probabilities
    across the monsoon leads (and models). -> 'below_normal_risk'/'normal'/'above_normal'."""
    rows = seasonal.get((str(state).strip().lower(), str(district).strip().lower()))
    if not rows:
        return None, None
    sel = [(pa, pb) for lead, pa, pb in rows if lead in monsoon_leads]
    if not sel:
        return None, None
    net = sum(a for a, _ in sel) / len(sel) - sum(b for _, b in sel) / len(sel)
    if net >= SEASONAL_TERCILE_MARGIN:
        ctx = "above_normal"
    elif net <= -SEASONAL_TERCILE_MARGIN:
        ctx = "below_normal_risk"
    else:
        ctx = "normal"
    return ctx, {"net": round(net, 3), "leads": len(sel)}


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
    ap.add_argument("--seasonal", default=str(DEFAULT_PLOTS / "seasonal_region.csv"),
                    help="Combined seasonal tercile CSV from forecast_region.py --districts (optional).")
    ap.add_argument("--probs", default=str(DEFAULT_PLOTS / "s2s_region_probs.csv"),
                    help="Weekly threshold-probability CSV from forecast_region_s2s.py --probs (optional).")
    ap.add_argument("--observed", default=str(DEFAULT_PLOTS / "observed_departures.csv"),
                    help="Observed rainfall-departures CSV from observed_departures.py (optional).")
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

    # seed default records for districts with model data but no JSON record yet
    existing = {(fc.get("state", "").strip().lower(), fc.get("district", "").strip().lower())
                for fc in forecasts}
    seeded = 0
    for key, d in s2s.items():
        if key not in existing:
            forecasts.append(_default_record(d.get("state", ""), d.get("district", "")))
            seeded += 1
    if seeded:
        print(f"seeded {seeded} new district record(s)")

    seasonal = load_seasonal(args.seasonal) if os.path.exists(args.seasonal) else {}
    print(f"seasonal districts: {len(seasonal)}")
    updated, skipped = merge(forecasts, s2s, seasonal)

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

    # observed rainfall departures (fills the fields the drought/monsoon scenarios key on)
    if os.path.exists(args.observed):
        obs = load_observed(args.observed)
        n_obs = 0
        for fc in forecasts:
            key = (fc.get("state", "").strip().lower(), fc.get("district", "").strip().lower())
            if key in obs:
                o = obs[key]
                for f in ("rainfall_since_june_1_pct_departure", "rainfall_last_7_days_pct_departure",
                          "rainfall_last_14_days_pct_departure", "monsoon_onset_status"):
                    fc[f] = o[f]
                fc["observed_source"] = (f"IMD 0.25deg gridded rainfall vs 1991-2020 normal, "
                                         f"asof {o['obs_asof']}")
                n_obs += 1
        print(f"observed departures applied to {n_obs} district(s)")
    else:
        print(f"(no observed CSV at {args.observed}; keeping default observed fields)")

    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(forecasts, fh, indent=2)

    print(f"\n[OK] updated {len(updated)} district(s): {', '.join(updated)}")
    if skipped:
        print(f"[--] no model data for {len(skipped)} (left unchanged): {', '.join(skipped)}")
    print(f"[->] wrote {args.json}")


if __name__ == "__main__":
    main()
