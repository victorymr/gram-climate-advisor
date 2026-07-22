#!/usr/bin/env python3
"""
Build a RELIABILITY CALIBRATION for the app's threshold odds, from the backtest.

Raw ensemble odds are the fraction of members crossing a threshold -- ensemble *confidence*,
not historical accuracy. The backtest showed the ensemble is under-dispersed, so those
odds are over-confident (a raw "80%" verified less than 80% of the time). This fits, per
threshold event x lead-week, a monotonic map  raw_p -> observed frequency  (reliability
curve, isotonic regression via pool-adjacent-violators) and writes it to
data/calibration.json. The app applies it at display time so the odds reflect how often
that forecast probability has actually verified.

Source: the GEFS 31-member ensemble backtest (2021-2025, own-climatology referenced) --
the largest, highest-weight ensemble. Caveat written into the file: the live odds are a
weighted GEFS+EC46 pool, so this is a close approximation, not an exact match; refit as
more member-matched backtests accrue.

    python backtest/build_calibration.py   ->  ../data/calibration.json
"""

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC)); sys.path.insert(0, str(HERE))
import metrics                                                          # noqa: E402
from metrics import EVENT_NAMES, EVENTS                                 # noqa: E402

OUT = FC.parent / "data" / "calibration.json"
NBINS = 10
MIN_BIN = 30            # min samples in a probability bin to trust it
MIN_EVENT = 500         # min samples for an (event, week) to calibrate at all


def isotonic(y, w):
    """Weighted isotonic (non-decreasing) fit via pool-adjacent-violators; value per point."""
    vals, wts, idx = list(map(float, y)), list(map(float, w)), [[i] for i in range(len(y))]
    i = 0
    while i < len(vals) - 1:
        if vals[i] <= vals[i + 1] + 1e-12:
            i += 1
        else:
            nv = (vals[i] * wts[i] + vals[i + 1] * wts[i + 1]) / (wts[i] + wts[i + 1])
            vals[i] = nv; wts[i] += wts[i + 1]; idx[i] += idx[i + 1]
            del vals[i + 1], wts[i + 1], idx[i + 1]
            i = max(i - 1, 0)
    fit = [0.0] * len(y)
    for v, ii in zip(vals, idx):
        for j in ii:
            fit[j] = v
    return fit


def curve(p, y):
    """Reliability curve -> (x = bin mean forecast p, y = isotonic-calibrated frequency)."""
    edges = np.linspace(0, 1, NBINS + 1)
    b = np.clip(np.digitize(p, edges) - 1, 0, NBINS - 1)
    xs, ys, ns = [], [], []
    for k in range(NBINS):
        m = b == k
        if m.sum() < MIN_BIN:
            continue
        xs.append(float(p[m].mean())); ys.append(float(y[m].mean())); ns.append(int(m.sum()))
    if len(xs) < 3:
        return None
    yfit = isotonic(ys, ns)
    # anchor the ends so interpolation covers [0,1]
    x = [0.0] + xs + [1.0]
    yv = [min(yfit[0], xs[0])] + yfit + [max(yfit[-1], xs[-1])]
    return {"x": [round(v, 4) for v in x], "y": [round(v, 4) for v in yv],
            "n": int(sum(ns))}


def main():
    metrics.COLL = HERE / "collapsed_reref"          # own-climatology-referenced GEFS ensemble
    df = metrics.load_pairs()
    print(f"fitting calibration from {len(df):,} samples ({df['init'].nunique()} inits)")
    events = {}
    for name, var, cmp, lvl in EVENTS:
        pc, yc = f"p_{name}", f"y_{name}"
        if pc not in df:
            continue
        per_week = {}
        for wk in range(1, 6):
            g = df[(df.variable == var) & (df.week == wk)][[pc, yc]].dropna()
            if len(g) < MIN_EVENT:
                continue
            c = curve(g[pc].to_numpy(float), g[yc].to_numpy(float))
            if c:
                per_week[str(wk)] = c
        if per_week:
            events[name] = per_week
            base = df[df.variable == var][yc].mean()
            print(f"  {name:9s}: weeks {sorted(per_week)}  (base rate {base:.2f})")

    OUT.write_text(json.dumps({
        "_meta": {
            "source": "GEFS 31-member ensemble backtest, 2021-2025, own-climatology referenced",
            "method": "isotonic reliability curve per (event, lead-week); raw_p -> observed freq",
            "caveat": "Live odds are a weighted GEFS+EC46 pool; this GEFS-based curve is a close "
                      "approximation. Falls back to identity where an (event, week) lacked samples.",
            "nbins": NBINS,
        },
        "events": events,
    }, indent=2))
    print(f"\nwrote -> {OUT}")


if __name__ == "__main__":
    main()
