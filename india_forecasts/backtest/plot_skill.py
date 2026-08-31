#!/usr/bin/env python3
"""
Plot backtest skill vs lead time: RMSE (with the climatology baseline) and Brier Skill
Score, for the forecasts referenced to each model's own climatology -- plus a
before/after panel showing what per-model referencing bought us.

Reuses metrics.load_pairs / det_scores / prob_scores (swapping metrics.COLL to score
either the ERA5-referenced 'collapsed' set or the own-referenced 'collapsed_reref' set).

    python backtest/plot_skill.py    ->  backtest/plots/*.png
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC))
sys.path.insert(0, str(HERE))
import metrics                                          # noqa: E402
from forecast_region_s2s import (WET_MM, DRY_MM, HEAVY_MM,   # noqa: E402
                                 DRYSPELL_MM, HOT_C)

PLOTS = HERE / "plots"
PLOTS.mkdir(exist_ok=True)
WEEKS = [1, 2, 3, 4, 5]

# colour-blind-safe (Okabe-Ito)
C = {"gefs": "#0072B2", "cfsv2": "#D55E00", "mme": "#009E73", "clim": "#999999"}
EVENT_C = {"wetter": "#0072B2", "drier": "#D55E00", "heavy": "#56B4E9",
           "dryspell": "#E69F00", "hot": "#CC79A7"}
EVENT_LABEL = {"wetter": f"wetter (>= {WET_MM:g})", "drier": f"drier (<= {DRY_MM:g})",
               "heavy": f"heavy rain (>= {HEAVY_MM:g})",
               "dryspell": f"dry spell (<= {DRYSPELL_MM:g})", "hot": f"hot (>= {HOT_C:g})"}

plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.axisbelow": True,
                     "axes.spines.top": False, "axes.spines.right": False})


def score_set(colldir):
    metrics.COLL = Path(colldir)
    df = metrics.load_pairs()
    det = metrics.det_scores(df, ["week", "variable"])
    prob = metrics.prob_scores(df, ["week", "variable"])
    # climatology RMSE baseline per (week, variable): forecast "0 anomaly"
    clim = (df.assign(sq=df["obs"] ** 2).groupby(["week", "variable"])["sq"]
            .mean().pow(0.5).rename("rmse_clim").reset_index())
    return det, prob, clim


def line(ax, x, y, **kw):
    ax.plot(x, y, marker="o", ms=4, lw=2, **kw)


def fig_rmse(det, clim):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, var, unit in ((axes[0], "precip", "mm/day"), (axes[1], "t2m", "°C")):
        for mdl in ("gefs", "cfsv2", "mme"):
            d = det[(det.variable == var) & (det.model == mdl)].sort_values("week")
            line(ax, d["week"], d["rmse"], color=C[mdl], label=mdl.upper())
        cb = clim[clim.variable == var].sort_values("week")
        ax.plot(cb["week"], cb["rmse_clim"], color=C["clim"], ls="--", lw=2,
                label="climatology")
        ax.set_title(f"{'Rainfall' if var == 'precip' else 'Temperature'} RMSE")
        ax.set_xlabel("lead (week)"); ax.set_ylabel(f"RMSE ({unit})")
        ax.set_xticks(WEEKS)
        ax.margins(x=0.05)
    axes[0].legend(frameon=False, fontsize=9)
    axes[1].annotate("below dashed = beats climatology", xy=(0.5, 0.04),
                     xycoords="axes fraction", ha="center", fontsize=8, color="#555")
    fig.suptitle("Forecast RMSE vs lead time  (own-climatology reference; "
                 "25 inits x 776 districts, 2021–2025)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "skill_rmse_vs_lead.png", bbox_inches="tight")
    plt.close(fig)


def fig_bss(prob):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    groups = (("precip", ["wetter", "drier", "heavy", "dryspell"], axes[0], "Rainfall thresholds"),
              ("t2m", ["hot"], axes[1], "Temperature threshold"))
    for var, events, ax, title in groups:
        p = prob[prob.variable == var].sort_values("week")
        for ev in events:
            col = f"bss_{ev}"
            if col in p:
                line(ax, p["week"], p[col], color=EVENT_C[ev], label=EVENT_LABEL[ev])
        ax.axhline(0, color="#333", lw=1)
        ax.set_title(f"Brier Skill Score — {title}")
        ax.set_xlabel("lead (week)"); ax.set_ylabel("BSS (vs climatology)")
        ax.set_xticks(WEEKS); ax.margins(x=0.05)
        ax.legend(frameon=False, fontsize=8, loc="upper right")
    axes[0].annotate("above 0 = skill", xy=(0.03, 0.93), xycoords="axes fraction",
                     fontsize=8, color="#555")
    fig.suptitle("Threshold-event skill vs lead time  (GEFS 31-member ensemble, "
                 "own-climatology reference)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "skill_bss_vs_lead.png", bbox_inches="tight")
    plt.close(fig)


def fig_beforeafter(det_e, det_o, prob_e, prob_o):
    """The payoff: RMSE skill score (RMSESS) and hot-week BSS, ERA5-ref vs own-ref."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    for var, col in (("precip", C["gefs"]), ("t2m", C["mme"])):
        de = det_e[(det_e.variable == var) & (det_e.model == "gefs")].sort_values("week")
        do = det_o[(det_o.variable == var) & (det_o.model == "gefs")].sort_values("week")
        lbl = "rainfall" if var == "precip" else "temperature"
        ax.plot(de["week"], de["rmsess"], color=col, ls="--", lw=2, marker="o", ms=4,
                alpha=0.5, label=f"{lbl}: ERA5 ref")
        ax.plot(do["week"], do["rmsess"], color=col, lw=2.4, marker="o", ms=5,
                label=f"{lbl}: own ref")
    ax.axhline(0, color="#333", lw=1)
    ax.set_title("GEFS RMSE skill score (RMSESS)")
    ax.set_xlabel("lead (week)"); ax.set_ylabel("RMSESS  (>0 = beats climatology)")
    ax.set_xticks(WEEKS); ax.legend(frameon=False, fontsize=8)

    ax = axes[1]
    pe = prob_e[prob_e.variable == "t2m"].sort_values("week")
    po = prob_o[prob_o.variable == "t2m"].sort_values("week")
    ax.plot(pe["week"], pe["bss_hot"], color=EVENT_C["hot"], ls="--", lw=2, marker="o",
            ms=4, alpha=0.5, label="hot-week BSS: ERA5 ref")
    ax.plot(po["week"], po["bss_hot"], color=EVENT_C["hot"], lw=2.4, marker="o", ms=5,
            label="hot-week BSS: own ref")
    ax.axhline(0, color="#333", lw=1)
    ax.set_title("Hot-week Brier skill")
    ax.set_xlabel("lead (week)"); ax.set_ylabel("BSS")
    ax.set_xticks(WEEKS); ax.legend(frameon=False, fontsize=8)
    fig.suptitle("Before / after referencing each model to its own climatology",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "skill_before_after.png", bbox_inches="tight")
    plt.close(fig)


def main():
    det_o, prob_o, clim = score_set(HERE / "collapsed_reref")
    det_e, prob_e, _ = score_set(HERE / "collapsed")
    fig_rmse(det_o, clim)
    fig_bss(prob_o)
    fig_beforeafter(det_e, det_o, prob_e, prob_o)
    print(f"wrote 3 figures -> {PLOTS}")
    for f in sorted(PLOTS.glob("skill_*.png")):
        print("  ", f.name)


if __name__ == "__main__":
    main()
