#!/usr/bin/env python3
"""
Score the backtest: join the collapsed model members (collapsed/<init>.nc) with the
observed truth (truth/<init>.nc) and compute deterministic + probabilistic skill,
stratified by lead-week x variable x zone x climate-state.

Deterministic (ensemble mean):  ACC (anomaly correlation), RMSE, RMSE skill score vs
                                climatology, bias.
Probabilistic (the ensemble) :  CRPS + CRPSS vs climatology; Brier score + BSS for the
                                app's thresholds (wetter/drier tercile lean, heavy rain,
                                dry spell, hot week); reliability bins; rank histogram.

Pure numpy (no xskillscore/properscoring dependency). Climatology reference = the
anomaly's own zero (anomalies are already vs the DOY normal), so a climatology forecast
is "0 anomaly" / base-rate probability -- the honest no-skill baseline.

Usage:
    python backtest/metrics.py                     # -> scores/*.csv
    python backtest/metrics.py --zone-only         # skip per-district detail
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
    ("wetter", "precip", "ge", WET_MM),
    ("drier",  "precip", "le", DRY_MM),
    ("heavy",  "precip", "ge", HEAVY_MM),
    ("dryspell", "precip", "le", DRYSPELL_MM),
    ("hot",    "t2m",    "ge", HOT_C),
]


def crps_ensemble(members, obs):
    """CRPS for one obs given ensemble members (1-D array). Energy-form estimator."""
    m = members[np.isfinite(members)]
    if m.size == 0 or not np.isfinite(obs):
        return np.nan
    term1 = np.mean(np.abs(m - obs))
    term2 = 0.5 * np.mean(np.abs(m[:, None] - m[None, :]))
    return term1 - term2


def _long_frame(models=("gefs", "cfsv2")):
    """Tidy per (init, district, week, variable) frame: ensemble members, mean, obs, tags."""
    rows = []
    for cpath in sorted(glob.glob(str(COLL / "*.nc"))):
        init = Path(cpath).stem
        tpath = TRUTH / f"{init}.nc"
        if not tpath.exists():
            continue
        fc, tr = xr.open_dataset(cpath), xr.open_dataset(tpath)
        state = fc["state"].values
        dist = fc["district_name"].values
        for var in ("precip", "t2m"):
            obsname = f"obs_{var}_anom"
            if obsname not in tr:
                continue
            obs = tr[obsname]                     # (district, week)
            # stack every model's members (gefs: member dim; cfsv2: single mean)
            memsets = []
            for mdl in models:
                vname = f"{mdl}_{var}_anom"
                if vname not in fc:
                    continue
                da = fc[vname]
                if "member" in da.dims:
                    memsets.append(da)            # (district, member, week)
                else:
                    memsets.append(da.expand_dims(member=[f"{mdl}_mean"]))
            if not memsets:
                continue
            allm = xr.concat([m.transpose("district", "member", "week") for m in memsets], dim="member")
            for wk in obs["week"].values:
                o = obs.sel(week=wk).values
                mm = allm.sel(week=wk).values      # (district, member)
                for di in range(o.shape[0]):
                    ov = o[di]
                    if not np.isfinite(ov):
                        continue
                    rows.append((init, state[di], dist[di], int(wk), var,
                                 mm[di], float(ov)))
        fc.close(); tr.close()
    df = pd.DataFrame(rows, columns=["init", "state", "district", "week", "variable", "members", "obs"])
    if df.empty:
        return df
    df["year"] = df["init"].str[:4].astype(int)
    # climate-state tags per init (enso / phase / monsoon note)
    tags = pd.read_csv(INITS_CSV)
    tags["init"] = tags["init_date"].str.replace("-", "", regex=False)
    df = df.merge(tags[["init", "phase", "enso", "monsoon_season_note"]], on="init", how="left")
    # district zone from the advisor coordinates (region column)
    coords = pd.read_csv(FC.parent / "data" / "district_coordinates.csv")
    if "region" in coords.columns:
        df = df.merge(coords[["state", "district", "region"]].rename(columns={"region": "zone"}),
                      on=["state", "district"], how="left")
    return df


def _det_scores(g):
    """ACC / RMSE / RMSESS / bias over a group (ensemble-mean vs obs)."""
    fc = np.array([np.nanmean(m) for m in g["members"]])
    ob = g["obs"].to_numpy()
    ok = np.isfinite(fc) & np.isfinite(ob)
    fc, ob = fc[ok], ob[ok]
    if fc.size < 3:
        return dict(n=fc.size, acc=np.nan, rmse=np.nan, rmsess=np.nan, bias=np.nan)
    acc = np.corrcoef(fc, ob)[0, 1] if fc.std() > 0 and ob.std() > 0 else np.nan
    rmse = float(np.sqrt(np.mean((fc - ob) ** 2)))
    rmse_clim = float(np.sqrt(np.mean(ob ** 2)))       # climatology forecast = 0 anomaly
    rmsess = 1 - rmse / rmse_clim if rmse_clim > 0 else np.nan
    return dict(n=fc.size, acc=acc, rmse=rmse, rmsess=rmsess, bias=float(np.mean(fc - ob)))


def _prob_scores(g):
    """CRPS/CRPSS + Brier/BSS for each threshold event over a group."""
    out = {}
    crps = np.array([crps_ensemble(np.asarray(m, float), o) for m, o in zip(g["members"], g["obs"])])
    crps_clim = np.array([abs(o) for o in g["obs"]], float)   # climo "ensemble" = {0}
    out["crps"] = float(np.nanmean(crps))
    out["crpss"] = float(1 - np.nanmean(crps) / np.nanmean(crps_clim)) if np.nanmean(crps_clim) > 0 else np.nan
    var = g["variable"].iloc[0]
    for name, evar, cmp, lvl in EVENTS:
        if evar != var:
            continue
        p, y = [], []
        for m, o in zip(g["members"], g["obs"]):
            m = np.asarray(m, float); m = m[np.isfinite(m)]
            if m.size == 0 or not np.isfinite(o):
                continue
            p.append(np.mean(m >= lvl if cmp == "ge" else m <= lvl))
            y.append(1.0 if (o >= lvl if cmp == "ge" else o <= lvl) else 0.0)
        p, y = np.array(p), np.array(y)
        if p.size < 5:
            continue
        base = y.mean()
        bs = float(np.mean((p - y) ** 2))
        bs_clim = float(np.mean((base - y) ** 2))
        out[f"brier_{name}"] = bs
        out[f"bss_{name}"] = float(1 - bs / bs_clim) if bs_clim > 0 else np.nan
        out[f"base_{name}"] = float(base)
    return out


def main():
    ap = argparse.ArgumentParser(description="Score the district backtest.")
    ap.add_argument("--by", nargs="+", default=["week", "variable"],
                    help="Grouping columns (e.g. week variable zone year).")
    args = ap.parse_args()

    df = _long_frame()
    if df.empty:
        sys.exit("No paired collapsed+truth data found. Run run_backtest.py and build_truth.py first.")
    print(f"scoring {len(df)} district-week-var samples from {df['init'].nunique()} inits")

    det = df.groupby(args.by).apply(lambda g: pd.Series(_det_scores(g))).reset_index()
    prob = df.groupby(args.by).apply(lambda g: pd.Series(_prob_scores(g))).reset_index()
    det.to_csv(SCORES / "deterministic.csv", index=False)
    prob.to_csv(SCORES / "probabilistic.csv", index=False)
    print(f"wrote {SCORES/'deterministic.csv'} and {SCORES/'probabilistic.csv'}")
    print("\nDeterministic (ACC / RMSESS by lead):")
    print(det.to_string(index=False))


if __name__ == "__main__":
    main()
