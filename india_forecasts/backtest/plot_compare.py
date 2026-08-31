#!/usr/bin/env python3
"""
Compare EC46 skill vs GEFS and CFSv2, by lead time. GEFS/CFSv2 are recomputed from the
own-climatology-referenced backtest (metrics on collapsed_reref); EC46 is read from
ec46_backtest.py's scores. Deterministic panels cover all three; probabilistic panels
cover the two models with ensembles (GEFS, EC46).

NOTE the samples differ (EC46: 2004-2020 monsoon reforecasts @ 1.5 deg; GEFS/CFSv2:
2021-2025 @ 0.25-0.5 deg), so read these as skill *levels* vs each model's own
climatology, not case-by-case -- stated on the figures.

    python backtest/plot_compare.py   ->  backtest/plots/compare_*.png
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
sys.path.insert(0, str(FC)); sys.path.insert(0, str(HERE))
import metrics                                                          # noqa: E402

PLOTS, SCORES = HERE / "plots", HERE / "scores"
PLOTS.mkdir(exist_ok=True)
WEEKS = [1, 2, 3, 4, 5]
C = {"gefs": "#0072B2", "cfsv2": "#D55E00", "ec46": "#009E73"}
LBL = {"gefs": "GEFS", "cfsv2": "CFSv2", "ec46": "EC46"}
plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.axisbelow": True,
                     "axes.spines.top": False, "axes.spines.right": False})
SAMPLE_NOTE = ("Different samples: EC46 = 2004–2020 monsoon reforecasts @1.5°; "
               "GEFS/CFSv2 = 2021–2025 @0.25–0.5°. Compare skill levels, not cases.")


def line(ax, d, col, model, marker="o"):
    d = d.sort_values("week")
    ax.plot(d["week"], d[col], color=C[model], lw=2.2, marker=marker, ms=5, label=LBL[model])


def gefs_cfsv2_scores():
    metrics.COLL = HERE / "collapsed_reref"
    df = metrics.load_pairs()
    det = metrics.det_scores(df, ["week", "variable"])
    prob = metrics.prob_scores(df, ["week", "variable"])
    return det, prob


def deterministic_fig(det_gc, ec_det):
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for j, (var, name) in enumerate((("precip", "Rainfall"), ("t2m", "Temperature"))):
        for i, (metric, ylab, ref) in enumerate(
                (("acc", "Anomaly correlation (ACC)", None),
                 ("rmsess", "RMSE skill score", 0.0))):
            ax = axes[i, j]
            for mdl in ("gefs", "cfsv2"):
                line(ax, det_gc[(det_gc.variable == var) & (det_gc.model == mdl)], metric, mdl)
            if ec_det is not None:
                line(ax, ec_det[ec_det.variable == var], metric, "ec46", marker="s")
            if ref is not None:
                ax.axhline(ref, color="#333", lw=0.9)
            ax.set_title(f"{name} — {metric.upper() if metric=='acc' else 'RMSESS'}")
            ax.set_xlabel("lead (week)"); ax.set_ylabel(ylab); ax.set_xticks(WEEKS)
    axes[0, 0].legend(frameon=False, fontsize=9)
    fig.suptitle("Deterministic skill vs lead: EC46 vs GEFS vs CFSv2", fontsize=12)
    fig.text(0.5, 0.005, SAMPLE_NOTE, ha="center", fontsize=8, color="#666")
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(PLOTS / "compare_deterministic.png", bbox_inches="tight")
    plt.close(fig)


def probabilistic_fig(prob_g, ec_prob):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    # CRPSS (both models with ensembles)
    ax = axes[0]
    for var, mk in (("precip", "o"), ("t2m", "s")):
        pg = prob_g[prob_g.variable == var].sort_values("week")
        ax.plot(pg["week"], pg["crpss"], color=C["gefs"], lw=2.2, marker=mk, ms=5,
                label=f"GEFS {var}")
        if ec_prob is not None:
            pe = ec_prob[ec_prob.variable == var].sort_values("week")
            ax.plot(pe["week"], pe["crpss"], color=C["ec46"], lw=2.2, marker=mk, ms=5,
                    ls="--", label=f"EC46 {var}")
    ax.axhline(0, color="#333", lw=0.9)
    ax.set_title("CRPS skill score (ensemble)"); ax.set_xlabel("lead (week)")
    ax.set_ylabel("CRPSS (vs climatology)"); ax.set_xticks(WEEKS)
    ax.legend(frameon=False, fontsize=8)
    # BSS for the two most useful events: dry spell (precip) and hot (t2m)
    ax = axes[1]
    for col, mk, lab in (("bss_dryspell", "o", "dry spell"), ("bss_hot", "s", "hot week")):
        pg = prob_g.dropna(subset=[col]).sort_values("week") if col in prob_g else pd.DataFrame()
        if len(pg):
            ax.plot(pg["week"], pg[col], color=C["gefs"], lw=2.2, marker=mk, ms=5, label=f"GEFS {lab}")
        if ec_prob is not None and col in ec_prob:
            pe = ec_prob.dropna(subset=[col]).sort_values("week")
            if len(pe):
                ax.plot(pe["week"], pe[col], color=C["ec46"], lw=2.2, marker=mk, ms=5, ls="--",
                        label=f"EC46 {lab}")
    ax.axhline(0, color="#333", lw=0.9)
    ax.set_title("Brier skill score (dry spell, hot week)"); ax.set_xlabel("lead (week)")
    ax.set_ylabel("BSS (vs climatology)"); ax.set_xticks(WEEKS)
    ax.legend(frameon=False, fontsize=8)
    fig.suptitle("Probabilistic skill vs lead: EC46 vs GEFS ensemble", fontsize=12)
    fig.text(0.5, 0.005, SAMPLE_NOTE, ha="center", fontsize=8, color="#666")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(PLOTS / "compare_probabilistic.png", bbox_inches="tight")
    plt.close(fig)


def main():
    det_gc, prob_g = gefs_cfsv2_scores()
    ec_det = pd.read_csv(SCORES / "ec46_deterministic.csv") if (SCORES / "ec46_deterministic.csv").exists() else None
    ec_prob = pd.read_csv(SCORES / "ec46_probabilistic.csv") if (SCORES / "ec46_probabilistic.csv").exists() else None
    deterministic_fig(det_gc, ec_det)
    probabilistic_fig(prob_g, ec_prob)
    print(f"wrote -> {PLOTS/'compare_deterministic.png'}")
    print(f"wrote -> {PLOTS/'compare_probabilistic.png'}"
          + ("" if ec_prob is not None else "  (EC46 prob missing -- run ec46_backtest with members first)"))


if __name__ == "__main__":
    main()
