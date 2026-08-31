#!/usr/bin/env python3
"""
Prototype an MME that down-weights CFSv2.

The current multi-model mean is an equal-weight average, but the backtest shows CFSv2
is worse than climatology at every lead (even after per-model bias removal), so it drags
the mean down. This sweeps the GEFS<->CFSv2 blend on the re-referenced (own-climatology)
backtest data and finds the weight that maximises skill.

  mme(a) = a * gefs_mean + (1 - a) * cfsv2          a = GEFS weight in [0, 1]
           a = 0.5  -> current equal-weight MME
           a = 1.0  -> GEFS only

Scores RMSE / ACC / RMSE-skill-score vs obs, per (variable, lead-week), and reports the
per-lead optimum plus a single practical weight per variable. Writes a CSV + a plot.

Caveat: the backtest has no EC46 (no hindcast), so this speaks only to the GEFS:CFSv2
relative weight. EC46's weight can't be validated here.

    python backtest/mme_weights.py
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

PLOTS, SCORES = HERE / "plots", HERE / "scores"
PLOTS.mkdir(exist_ok=True)
ALPHAS = np.round(np.linspace(0.0, 1.0, 51), 3)         # GEFS weight
WEEKS = [1, 2, 3, 4, 5]


def rmse(f, o):
    m = np.isfinite(f) & np.isfinite(o)
    return float(np.sqrt(np.mean((f[m] - o[m]) ** 2)))


def acc(f, o):
    m = np.isfinite(f) & np.isfinite(o)
    f, o = f[m], o[m]
    return float(np.corrcoef(f, o)[0, 1]) if f.std() > 0 and o.std() > 0 else np.nan


def blend(g, c, a):
    return a * g + (1 - a) * c


def main():
    metrics.COLL = HERE / "collapsed_reref"             # own-climatology reference
    df = metrics.load_pairs()
    print(f"{len(df):,} samples; sweeping GEFS weight a in [0,1] "
          f"(a=0.5 equal-weight, a=1 GEFS-only)\n")

    # per (variable, lead) skill curve over alpha
    curves, rows = {}, []
    for var in ("precip", "t2m"):
        for wk in WEEKS:
            g = df[(df.variable == var) & (df.week == wk)]
            gf, cf, o = g["gefs"].to_numpy(float), g["cfsv2"].to_numpy(float), g["obs"].to_numpy(float)
            rc = rmse(np.zeros_like(o), o)              # climatology RMSE (zero anomaly)
            rmsess = np.array([1 - rmse(blend(gf, cf, a), o) / rc for a in ALPHAS])
            curves[(var, wk)] = rmsess
            a_best = float(ALPHAS[int(np.argmax(rmsess))])
            rows.append(dict(variable=var, week=wk,
                             rmsess_equal=float(rmsess[np.where(ALPHAS == 0.5)[0][0]]),
                             rmsess_gefs=float(rmsess[-1]),
                             a_best=a_best, rmsess_best=float(rmsess.max()),
                             acc_equal=acc(blend(gf, cf, 0.5), o),
                             acc_gefs=acc(gf, o), acc_best=acc(blend(gf, cf, a_best), o)))
    tab = pd.DataFrame(rows)

    # single practical weight per variable: the a that maximises the mean RMSESS across leads
    globe = {}
    for var in ("precip", "t2m"):
        stacked = np.vstack([curves[(var, wk)] for wk in WEEKS]).mean(axis=0)
        globe[var] = float(ALPHAS[int(np.argmax(stacked))])

    with pd.option_context("display.width", 200):
        print("=== RMSE skill score by lead: equal-weight vs GEFS-only vs per-lead optimum ===")
        print(tab.round(3).to_string(index=False))
    print("\n=== single recommended GEFS weight (max mean-over-leads RMSESS) ===")
    for var in ("precip", "t2m"):
        print(f"  {var:7s}: a* = {globe[var]:.2f}   "
              f"(CFSv2 weight {1 - globe[var]:.2f})")
    tab.to_csv(SCORES / "mme_weights.csv", index=False)

    # plot: RMSESS vs GEFS weight, one line per lead, per variable
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    for ax, var, unit in ((axes[0], "precip", "Rainfall"), (axes[1], "t2m", "Temperature")):
        for wk in WEEKS:
            ax.plot(ALPHAS, curves[(var, wk)], lw=1.8, label=f"week {wk}")
        ax.axvline(0.5, color="#999", ls=":", lw=1.5)
        ax.axvline(globe[var], color="#333", ls="--", lw=1.5)
        ax.text(0.5, ax.get_ylim()[1], " equal", color="#777", fontsize=8, va="top")
        ax.text(globe[var], ax.get_ylim()[0], f" a*={globe[var]:.2f}", color="#333",
                fontsize=8, va="bottom")
        ax.axhline(0, color="#333", lw=0.8)
        ax.set_title(f"{unit}: skill vs GEFS weight")
        ax.set_xlabel("GEFS weight  a   (CFSv2 weight = 1 - a)")
        ax.set_ylabel("RMSE skill score (vs climatology)")
        ax.grid(alpha=0.3)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, ncol=2)
    fig.suptitle("Down-weighting CFSv2 in the multi-model mean  "
                 "(own-climatology reference; a=0.5 is today's equal weight)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "mme_weight_sweep.png", bbox_inches="tight")
    plt.close(fig)
    print(f"\nwrote {SCORES/'mme_weights.csv'} and {PLOTS/'mme_weight_sweep.png'}")


if __name__ == "__main__":
    main()
