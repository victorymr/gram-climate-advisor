#!/usr/bin/env python3
"""
Build the per-lead-week FORECAST SKILL table that calibrates the app's confidence labels.

The advisor shows, per week, a rainfall category (drier / near normal / wetter, at
+-3 mm/day) and a temperature category (+-1.5 degC), and its risk scenarios fire on those
same weekly signals. Until now the "Confidence" label was a fixed lead-time heuristic
(week-1 trigger -> High). This script replaces that guess with MEASURED skill from the
district backtest: for every (variable, lead-week[, zone]) it records

  * acc / rmsess      -- anomaly correlation and RMSE skill of the forecast the app ships
                          (the MME_WEIGHTS-weighted GEFS+CFSv2 mean, own-climatology referenced)
  * per category      -- how often the displayed category VERIFIED when it was forecast
                          (hit_rate = P(obs in cat | fc in cat)), against the chance rate
                          (base_rate = P(obs in cat)), and how often it was forecast (n_fc)
  * tier              -- High / Medium / Low, from the anomaly correlation (see TIER_RULE)

Written to data/forecast_skill.json; read at runtime by src/skill.py, which the rule engine
(scenario confidence) and the app (per-week outlook confidence) consume. Also writes
scores/skill_summary.csv for inspection.

Caveats (also recorded in the JSON):
  * 2021-2025, 25 inits (May-Sep), 785 districts: a monsoon-season skill estimate.
  * The backtest has GEFS + CFSv2 only; the live MME also carries EC46 (no 2021-25
    reforecast). EC46's own 2004-20 reforecast skill (scores/ec46_deterministic.csv) is
    included under "models" for comparison -- it is similar to or better than GEFS, so the
    table is, if anything, slightly conservative for the live blend.

    python backtest/build_skill.py      ->  ../data/forecast_skill.json
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC)); sys.path.insert(0, str(HERE))
import metrics                                                          # noqa: E402
from forecast_region_s2s import MME_WEIGHTS, HEAVY_MM, HOT_C            # noqa: E402

OUT = FC.parent / "data" / "forecast_skill.json"
SUMMARY = HERE / "scores" / "skill_summary.csv"
WEEKS = [1, 2, 3, 4, 5]
MIN_N = 500             # samples needed before a (variable, week, zone) cell is trusted
MIN_N_CAT = 100         # forecasts of a category needed before its hit rate is reported

# Category thresholds: exactly what the app displays / the rules key on.
RAIN_ABOVE, RAIN_BELOW = 3.0, -3.0     # scripts/import_model_forecasts.rain_signal, rules.py
TMAX_ABOVE, TMAX_BELOW = HOT_C, -HOT_C  # tmax_signal (+-1.5 degC)
CATEGORIES = {
    "precip": {
        "below": lambda a: a <= RAIN_BELOW,                     # "drier" / dry-week trigger
        "near":  lambda a: (a > RAIN_BELOW) & (a < RAIN_ABOVE),
        "above": lambda a: a >= RAIN_ABOVE,                     # "wetter"
        "heavy": lambda a: a >= HEAVY_MM,                       # excess-rain trigger (+7)
    },
    "t2m": {
        "below": lambda a: a <= TMAX_BELOW,
        "near":  lambda a: (a > TMAX_BELOW) & (a < TMAX_ABOVE),
        "above": lambda a: a >= TMAX_ABOVE,                     # heat-stress trigger (+1.5)
    },
}

# Confidence tier from anomaly correlation. ACC ~0.5-0.6 is the conventional floor for
# "useful" deterministic skill; ~0.3 is where a signal is still distinguishable from noise
# at this sample size; below that the forecast is close to climatology.
TIER_RULE = {"High": 0.50, "Medium": 0.30}      # acc >= value -> tier; else Low


def tier_for(acc):
    if acc is None or not np.isfinite(acc):
        return None
    for name, lo in TIER_RULE.items():
        if acc >= lo:
            return name
    return "Low"


def _acc(f, o):
    ok = np.isfinite(f) & np.isfinite(o)
    f, o = f[ok], o[ok]
    if f.size < 3 or f.std() == 0 or o.std() == 0:
        return np.nan
    return float(np.corrcoef(f, o)[0, 1])


def _rmsess(f, o):
    ok = np.isfinite(f) & np.isfinite(o)
    f, o = f[ok], o[ok]
    if f.size < 3:
        return np.nan
    rc = np.sqrt(np.mean(o ** 2))
    return float(1 - np.sqrt(np.mean((f - o) ** 2)) / rc) if rc > 0 else np.nan


def cell(g, fcol):
    """Skill record for one (variable, week[, zone]) group of paired rows."""
    f, o = g[fcol].to_numpy(float), g["obs"].to_numpy(float)
    var = g["variable"].iloc[0]
    rec = {"n": int(np.isfinite(f).sum()),
           "acc": round(_acc(f, o), 3), "rmsess": round(_rmsess(f, o), 3)}
    rec["tier"] = tier_for(rec["acc"])
    cats = {}
    for name, fn in CATEGORIES[var].items():
        fc_in, ob_in = fn(f), fn(o)
        n_fc = int(fc_in.sum())
        c = {"base_rate": round(float(ob_in.mean()), 3), "n_fc": n_fc}
        if n_fc >= MIN_N_CAT:
            c["hit_rate"] = round(float(ob_in[fc_in].mean()), 3)
        cats[name] = c
    rec["categories"] = cats
    return rec


def model_acc_table(df):
    """ACC by (variable, week) for each candidate forecast -- for the JSON 'models' block."""
    out = {}
    for m in ("gefs", "cfsv2", "mme_equal", "mme_weighted"):
        col = {"mme_equal": "mme", "mme_weighted": "mme_w"}.get(m, m)
        out[m] = {var: {str(w): round(_acc(g[col].to_numpy(float), g["obs"].to_numpy(float)), 3)
                        for w, g in df[df.variable == var].groupby("week")}
                  for var in ("precip", "t2m")}
    ec = HERE / "scores" / "ec46_deterministic.csv"
    if ec.exists():
        e = pd.read_csv(ec)
        out["ec46_2004_2020"] = {var: {str(int(r.week)): round(float(r.acc), 3)
                                       for r in e[e.variable == var].itertuples()}
                                 for var in ("precip", "t2m")}
    return out


def main():
    metrics.COLL = HERE / "collapsed_reref"          # own-climatology-referenced forecasts
    df = metrics.load_pairs()
    if df.empty:
        sys.exit("no paired backtest data (run run_backtest.py, rereference.py, build_truth.py)")
    # The MME the app ships: MME_WEIGHTS-weighted mean of the models present. In the
    # backtest that is GEFS (ensemble mean) + CFSv2; CFSv2 falls back to GEFS where missing.
    wg, wc = MME_WEIGHTS["gefs"], MME_WEIGHTS["cfsv2"]
    c = df["cfsv2"].where(np.isfinite(df["cfsv2"]), df["gefs"])
    df["mme_w"] = (wg * df["gefs"] + wc * c) / (wg + wc)
    n_inits, years = df["init"].nunique(), sorted(df["year"].unique())
    print(f"{len(df):,} samples, {n_inits} inits {years[0]}-{years[-1]}, "
          f"{df['district'].nunique()} districts; GEFS:CFSv2 weight {wg}:{wc}")

    national, zones, rows = {}, {}, []
    for (var, wk), g in df.groupby(["variable", "week"]):
        rec = cell(g, "mme_w")
        national.setdefault(var, {})[str(int(wk))] = rec
        rows.append(dict(scope="India", variable=var, week=int(wk), **{
            k: v for k, v in rec.items() if k != "categories"},
            **{f"{cn}_hit": cv.get("hit_rate") for cn, cv in rec["categories"].items()},
            **{f"{cn}_base": cv["base_rate"] for cn, cv in rec["categories"].items()}))
    if "zone" in df:
        for (zone, var, wk), g in df.dropna(subset=["zone"]).groupby(["zone", "variable", "week"]):
            if len(g) < MIN_N:
                continue
            rec = cell(g, "mme_w")
            zones.setdefault(zone, {}).setdefault(var, {})[str(int(wk))] = rec
            rows.append(dict(scope=zone, variable=var, week=int(wk), **{
                k: v for k, v in rec.items() if k != "categories"},
                **{f"{cn}_hit": cv.get("hit_rate") for cn, cv in rec["categories"].items()},
                **{f"{cn}_base": cv["base_rate"] for cn, cv in rec["categories"].items()}))

    out = {
        "_meta": {
            "source": f"District backtest: GEFS 31-member ensemble mean + CFSv2, weighted "
                      f"{wg}:{wc} as in the live MME, own-climatology referenced; truth = IMD "
                      f"gridded rainfall/temperature (weekly anomalies vs day-of-year normal).",
            "period": f"{years[0]}-{years[-1]}, {n_inits} inits (May-Sep), "
                      f"{df['district'].nunique()} districts",
            "tier_rule": {"metric": "acc", **TIER_RULE, "else": "Low"},
            "categories": {
                "precip": f"below <= {RAIN_BELOW:g}, above >= {RAIN_ABOVE:g}, heavy >= {HEAVY_MM:g} mm/day",
                "t2m": f"below <= {TMAX_BELOW:g}, above >= {TMAX_ABOVE:g} degC",
            },
            "hit_rate": "P(observed category | forecast category); base_rate = P(observed category)",
            "caveat": "Backtest blend is GEFS+CFSv2; the live MME also includes EC46 (no 2021-25 "
                      "reforecast). EC46's 2004-20 reforecast skill (see models.ec46_2004_2020) is "
                      "similar or better, so these tiers are if anything slightly conservative.",
            "min_n_zone": MIN_N,
        },
        "weeks": WEEKS,
        "national": national,
        "zones": zones,
        "models": model_acc_table(df),
    }
    OUT.write_text(json.dumps(out, indent=1))
    SUMMARY.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(SUMMARY, index=False)

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        t = pd.DataFrame(rows)
        t = t[t.scope == "India"].set_index(["variable", "week"])
        print("\n=== National skill of the shipped MME by lead (own-ref) ===")
        print(t[[c for c in ("n", "acc", "rmsess", "tier", "below_hit", "below_base",
                              "above_hit", "above_base", "heavy_hit", "heavy_base")
                 if c in t]].to_string())
        z = pd.DataFrame(rows)
        z = z[z.scope != "India"].pivot_table(index="scope", columns=["variable", "week"],
                                              values="tier", aggfunc="first")
        print("\n=== Tier by zone ===")
        print(z.to_string())
    print(f"\nwrote -> {OUT}\n      -> {SUMMARY}")


if __name__ == "__main__":
    main()
