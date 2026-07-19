#!/usr/bin/env python3
"""
Score the backtest: join the collapsed model forecasts (collapsed/<init>.nc) with the
observed IMD truth (truth/<init>.nc) and compute deterministic + probabilistic skill,
stratified by lead-week x variable x zone x climate-state.

What is scored, and why:
  * DETERMINISTIC -- ACC, RMSE, RMSE skill score, bias -- for three forecasts:
      gefs  (31-member ensemble mean), cfsv2 (single deterministic run),
      mme   (mean of the two = what the app shows as the multi-model mean).
  * PROBABILISTIC -- CRPS/CRPSS, Brier/BSS on the app's own thresholds, reliability
    bins and a rank histogram -- from the GEFS 31-member ensemble ONLY. CFSv2 is a
    single field, not an ensemble draw, so pooling it as a "member" would distort the
    distribution (and let GEFS outvote it 31:1). The odds the app shows come from real
    ensemble members, so that is what we verify.

Reference/baseline: anomalies are already vs the day-of-year normal, so a climatology
forecast is "zero anomaly" (and base-rate probability). Skill scores are against that.

Outputs (scores/):
  deterministic.csv   ACC/RMSE/RMSESS/bias by group x model
  probabilistic.csv   CRPS/CRPSS + Brier/BSS per threshold event by group
  reliability.csv     forecast-probability bin vs observed frequency (per event)
  rank_histogram.csv  ensemble spread calibration (flat = well dispersed)

Usage:
    python backtest/metrics.py                       # standard strata + summary
    python backtest/metrics.py --by week variable zone
"""

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC))
from forecast_region_s2s import WET_MM, DRY_MM, HEAVY_MM, DRYSPELL_MM, HOT_C  # noqa: E402

COLL, TRUTH, SCORES = HERE / "collapsed", HERE / "truth", HERE / "scores"
SCORES.mkdir(exist_ok=True)
INITS_CSV = HERE / "inits.csv"

# threshold events scored with Brier/BSS: (name, variable, comparison, level)
EVENTS = [
    ("wetter",   "precip", "ge", WET_MM),
    ("drier",    "precip", "le", DRY_MM),
    ("heavy",    "precip", "ge", HEAVY_MM),
    ("dryspell", "precip", "le", DRYSPELL_MM),
    ("hot",      "t2m",    "ge", HOT_C),
]
EVENT_NAMES = [e[0] for e in EVENTS]


def crps_ensemble(M, o):
    """CRPS per row: M (n, m) ensemble members, o (n,) observations.

    Uses the sorted identity  E|X-X'| = (2/m^2) * sum_i (2i-m-1) * x_(i), so this is
    O(m log m) per row and fully vectorised across rows.
    """
    Ms = np.sort(M, axis=1)
    n, m = Ms.shape
    t1 = np.mean(np.abs(Ms - o[:, None]), axis=1)                 # E|X - o|
    i = np.arange(1, m + 1)
    t2 = (2.0 / (m * m)) * ((2 * i - m - 1) * Ms).sum(axis=1)     # E|X - X'|
    return t1 - 0.5 * t2


def _event_mask(vals, cmp, lvl):
    return vals >= lvl if cmp == "ge" else vals <= lvl


def load_pairs():
    """Tidy per (init, district, week, variable) frame with per-row derived scores.

    Derived at load time (vectorised per init, where the member count is constant) so
    all downstream grouping is plain aggregation.
    """
    frames = []
    for cpath in sorted(glob.glob(str(COLL / "*.nc"))):
        init = Path(cpath).stem
        tpath = TRUTH / f"{init}.nc"
        if not tpath.exists():
            continue
        fc, tr = xr.open_dataset(cpath), xr.open_dataset(tpath)
        state = np.asarray(fc["state"].values)
        dist = np.asarray(fc["district_name"].values)
        weeks = np.asarray(fc["week"].values)
        for var in ("precip", "t2m"):
            gname, cname, oname = f"gefs_{var}_anom", f"cfsv2_{var}_anom", f"obs_{var}_anom"
            if gname not in fc or oname not in tr:
                continue
            G = fc[gname].transpose("district", "week", "member").values   # (D, W, M)
            O = tr[oname].transpose("district", "week").values             # (D, W)
            C = (fc[cname].transpose("district", "week").values
                 if cname in fc else np.full(O.shape, np.nan))
            D, W, M = G.shape
            n = D * W
            Gf, Of, Cf = G.reshape(n, M), O.reshape(n), C.reshape(n)
            gmean = np.nanmean(Gf, axis=1)

            ok = np.isfinite(Of) & np.isfinite(Gf).all(axis=1)
            if not ok.any():
                continue
            Gf, Of, Cf, gmean = Gf[ok], Of[ok], Cf[ok], gmean[ok]
            d_idx = np.repeat(np.arange(D), W)[ok]
            w_idx = np.tile(weeks, D)[ok]

            df = pd.DataFrame({
                "init": init, "variable": var,
                "state": state[d_idx], "district": dist[d_idx], "week": w_idx.astype(int),
                "gefs": gmean, "cfsv2": Cf, "obs": Of,
            })
            df["mme"] = np.nanmean(np.vstack([gmean, Cf]), axis=0)
            df["crps"] = crps_ensemble(Gf, Of)
            df["crps_clim"] = np.abs(Of)                 # climatology "ensemble" = {0}
            df["rank"] = (Gf < Of[:, None]).sum(axis=1)  # obs rank among members
            df["n_members"] = M
            for name, evar, cmp, lvl in EVENTS:
                if evar != var:
                    continue
                df[f"p_{name}"] = _event_mask(Gf, cmp, lvl).mean(axis=1)
                df[f"y_{name}"] = _event_mask(Of, cmp, lvl).astype(float)
            frames.append(df)
        fc.close(); tr.close()

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["year"] = df["init"].str[:4].astype(int)
    tags = pd.read_csv(INITS_CSV)
    tags["init"] = tags["init_date"].str.replace("-", "", regex=False)
    df = df.merge(tags[["init", "phase", "enso", "monsoon_season_note"]], on="init", how="left")
    coords = pd.read_csv(FC.parent / "data" / "district_coordinates.csv")
    if "region" in coords.columns:
        df = df.merge(coords[["state", "district", "region"]].rename(columns={"region": "zone"}),
                      on=["state", "district"], how="left")
    return df


def _keyrec(by, keys):
    return dict(zip(by, keys if isinstance(keys, tuple) else (keys,)))


def det_scores(df, by):
    """ACC / RMSE / RMSESS / bias per group, for each of gefs / cfsv2 / mme."""
    out = []
    for model in ("gefs", "cfsv2", "mme"):
        for keys, g in df.groupby(by, dropna=False):
            f, o = g[model].to_numpy(float), g["obs"].to_numpy(float)
            ok = np.isfinite(f) & np.isfinite(o)
            f, o = f[ok], o[ok]
            if f.size < 3:
                continue
            rmse = float(np.sqrt(np.mean((f - o) ** 2)))
            rmse_clim = float(np.sqrt(np.mean(o ** 2)))          # climatology = zero anomaly
            rec = _keyrec(by, keys)
            rec.update(model=model, n=int(f.size),
                       acc=float(np.corrcoef(f, o)[0, 1]) if f.std() > 0 and o.std() > 0 else np.nan,
                       rmse=rmse,
                       rmsess=float(1 - rmse / rmse_clim) if rmse_clim > 0 else np.nan,
                       bias=float(np.mean(f - o)))
            out.append(rec)
    return pd.DataFrame(out)


def prob_scores(df, by):
    """CRPS/CRPSS + Brier/BSS per threshold event, per group (GEFS ensemble)."""
    out = []
    for keys, g in df.groupby(by, dropna=False):
        rec = _keyrec(by, keys)
        rec["n"] = int(len(g))
        c, cc = float(np.nanmean(g["crps"])), float(np.nanmean(g["crps_clim"]))
        rec["crps"] = c
        rec["crpss"] = float(1 - c / cc) if cc > 0 else np.nan
        for name in EVENT_NAMES:
            pc, yc = f"p_{name}", f"y_{name}"
            if pc not in g or g[pc].isna().all():
                continue
            p, y = g[pc].to_numpy(float), g[yc].to_numpy(float)
            ok = np.isfinite(p) & np.isfinite(y)
            p, y = p[ok], y[ok]
            if p.size < 20:
                continue
            base = float(y.mean())
            bs = float(np.mean((p - y) ** 2))
            bs_clim = float(np.mean((base - y) ** 2))
            rec[f"base_{name}"] = base
            rec[f"brier_{name}"] = bs
            rec[f"bss_{name}"] = float(1 - bs / bs_clim) if bs_clim > 0 else np.nan
        out.append(rec)
    return pd.DataFrame(out)


def reliability(df, nbins=10):
    """Forecast-probability bin vs observed frequency, per event x lead-week."""
    edges = np.linspace(0, 1, nbins + 1)
    rows = []
    for name in EVENT_NAMES:
        pc, yc = f"p_{name}", f"y_{name}"
        if pc not in df:
            continue
        sub = df[[pc, yc, "week"]].dropna()
        for wk, g in sub.groupby("week"):
            b = np.clip(np.digitize(g[pc], edges) - 1, 0, nbins - 1)
            for k in range(nbins):
                m = b == k
                if m.sum() < 10:
                    continue
                rows.append(dict(event=name, week=int(wk),
                                 bin_lo=float(edges[k]), bin_hi=float(edges[k + 1]),
                                 n=int(m.sum()),
                                 mean_forecast_p=float(g[pc][m].mean()),
                                 observed_freq=float(g[yc][m].mean())))
    return pd.DataFrame(rows)


def rank_histogram(df):
    """Counts of the obs rank among ensemble members (flat = well-dispersed)."""
    rows = []
    for (var, wk), g in df.groupby(["variable", "week"]):
        m = int(g["n_members"].iloc[0])
        cnt = np.bincount(g["rank"].to_numpy(int), minlength=m + 1)
        tot = cnt.sum()
        for r, c in enumerate(cnt):
            rows.append(dict(variable=var, week=int(wk), rank=r, count=int(c),
                             frac=float(c / tot) if tot else np.nan))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Score the district backtest.")
    ap.add_argument("--by", nargs="+", default=["week", "variable"],
                    help="Primary grouping (default: week variable).")
    args = ap.parse_args()

    df = load_pairs()
    if df.empty:
        sys.exit("No paired collapsed+truth data found. Run run_backtest.py and build_truth.py first.")
    print(f"scoring {len(df):,} district-week-variable samples "
          f"from {df['init'].nunique()} inits x {df['district'].nunique()} districts")

    det = det_scores(df, args.by)
    prob = prob_scores(df, args.by)
    det.to_csv(SCORES / "deterministic.csv", index=False)
    prob.to_csv(SCORES / "probabilistic.csv", index=False)
    reliability(df).to_csv(SCORES / "reliability.csv", index=False)
    rank_histogram(df).to_csv(SCORES / "rank_histogram.csv", index=False)
    for extra, fname in ((["week", "variable", "zone"], "deterministic_by_zone.csv"),
                         (["week", "variable", "enso"], "deterministic_by_enso.csv")):
        det_scores(df, extra).to_csv(SCORES / fname, index=False)

    print(f"\nwrote -> {SCORES}")
    with pd.option_context("display.width", 220, "display.max_columns", 60):
        print("\n=== Deterministic skill by lead (ACC / RMSESS) ===")
        print(det.pivot_table(index=["variable", "week"], columns="model",
                              values=["acc", "rmsess"]).round(3).to_string())
        print("\n=== Probabilistic skill by lead (GEFS 31-member ensemble) ===")
        cols = ["variable", "week", "n", "crps", "crpss"] + \
               [c for c in prob.columns if c.startswith("bss_")]
        print(prob[[c for c in cols if c in prob.columns]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
