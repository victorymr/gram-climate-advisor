#!/usr/bin/env python3
"""
Does each model's bias still matter once it is compared to ITS OWN history?

The pipeline anomalises every model against one shared ERA5 climatology
(forecast_region_s2s.anomalise), NOT against each model's own hindcast climatology.
So any model-vs-ERA5 mean offset survives into the reported anomaly -- and hence into
the "wetter / drier than normal" wording the app shows.

This re-references each model to its own climatology, estimated from the backtest
sample per (district, lead-week) and applied LEAVE-ONE-INIT-OUT so the correction is
never fitted on the case it scores. It then reports, before vs after:

  bias            mean(forecast - obs)
  acc / rmsess    skill (ACC is bias-immune, RMSESS is not)
  P(said drier)   fraction of district-weeks the forecast calls drier-than-normal
                  (anomaly <= DRY_MM), against the observed base rate -- i.e. does the
                  product over-report "drier than normal"?

Usage:  python backtest/bias_check.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from forecast_region_s2s import WET_MM, DRY_MM          # noqa: E402
from metrics import load_pairs, SCORES                  # noqa: E402

MODELS = ("gefs", "cfsv2", "mme")


def loo_own_climatology(df, col):
    """Leave-one-init-out mean of the model's own anomaly per (district, week, variable).

    This is the model's own climatology expressed in ERA5-anomaly space: if the model
    agreed with ERA5 on average it would be ~0. Subtracting it re-references the model
    to its own history without ever using the observations.
    """
    g = df.groupby(["district", "state", "week", "variable"])[col]
    s, n = g.transform("sum"), g.transform("count")
    return (s - df[col]) / (n - 1)


def score(f, o):
    ok = np.isfinite(f) & np.isfinite(o)
    f, o = f[ok], o[ok]
    if f.size < 3:
        return dict(n=0, acc=np.nan, rmse=np.nan, rmsess=np.nan, bias=np.nan)
    rmse = float(np.sqrt(np.mean((f - o) ** 2)))
    rmse_clim = float(np.sqrt(np.mean(o ** 2)))
    return dict(n=int(f.size),
                acc=float(np.corrcoef(f, o)[0, 1]) if f.std() > 0 and o.std() > 0 else np.nan,
                rmse=rmse,
                rmsess=float(1 - rmse / rmse_clim) if rmse_clim > 0 else np.nan,
                bias=float(np.mean(f - o)))


def main():
    df = load_pairs()
    if df.empty:
        sys.exit("No paired data. Run run_backtest.py and build_truth.py first.")
    p = df[df["variable"] == "precip"].copy()
    print(f"precip samples: {len(p):,}  ({p['init'].nunique()} inits x {p['district'].nunique()} districts)\n")

    for m in MODELS:
        p[f"{m}_corr"] = p[m] - loo_own_climatology(p, m)

    rows = []
    for m in MODELS:
        for tag, col in ((f"{m} (vs ERA5 clim, as shipped)", m),
                         (f"{m} (vs own history, LOO)", f"{m}_corr")):
            f, o = p[col].to_numpy(float), p["obs"].to_numpy(float)
            r = score(f, o)
            ok = np.isfinite(f) & np.isfinite(o)
            r["said_drier"] = float(np.mean(f[ok] <= DRY_MM))
            r["said_wetter"] = float(np.mean(f[ok] >= WET_MM))
            r["forecast"] = tag
            rows.append(r)
    obs = p["obs"].to_numpy(float)
    obs = obs[np.isfinite(obs)]
    base_dry, base_wet = float(np.mean(obs <= DRY_MM)), float(np.mean(obs >= WET_MM))

    out = pd.DataFrame(rows)[["forecast", "n", "bias", "acc", "rmsess", "said_drier", "said_wetter"]]
    print("=== Weekly rainfall anomaly: as-shipped vs re-referenced to each model's own history ===")
    print(out.round(3).to_string(index=False))
    print(f"\nOBSERVED base rate:  drier-than-normal {base_dry:.3f}   wetter-than-normal {base_wet:.3f}")
    print("(said_drier / said_wetter are the fractions the forecast would report; compare to the base rates)")

    # per-lead view of the correction's effect on the categorical call
    print("\n=== P(reports 'drier than normal') by lead -- MME, before vs after ===")
    per = []
    for wk, g in p.groupby("week"):
        o = g["obs"].to_numpy(float)
        per.append(dict(week=int(wk),
                        obs_base=float(np.mean(o <= DRY_MM)),
                        mme_as_shipped=float(np.mean(g["mme"].to_numpy(float) <= DRY_MM)),
                        mme_own_history=float(np.mean(g["mme_corr"].to_numpy(float) <= DRY_MM)),
                        cfsv2_as_shipped=float(np.mean(g["cfsv2"].to_numpy(float) <= DRY_MM)),
                        cfsv2_own_history=float(np.mean(g["cfsv2_corr"].to_numpy(float) <= DRY_MM))))
    print(pd.DataFrame(per).round(3).to_string(index=False))

    out.to_csv(SCORES / "bias_check.csv", index=False)
    print(f"\nwrote -> {SCORES/'bias_check.csv'}")


if __name__ == "__main__":
    main()
