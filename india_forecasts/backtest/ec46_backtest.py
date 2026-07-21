#!/usr/bin/env python3
"""
Backtest EC46 (ECMWF extended-range) skill against IMD observations, to put a MEASURED
number on EC46's role in the multi-model mean instead of assuming it.

Uses the S2S reforecasts from download_ec46_reforecast.py over hindcast years 2004-2020
(IMD obs cached), anomalised vs EC46's own reforecast climatology exactly as the live
pipeline does; obs are IMD weekly district anomalies vs the 1991-2020 DOY normal.

Two phases (truth is cached to backtest/truth_ec46/ so it is built only once):
  * DETERMINISTIC (always): ACC / RMSE / RMSESS / bias of the ensemble mean (11-member if
    the perturbed members are present, else the control).
  * PROBABILISTIC (when ec46rfm_*_members.nc exist): CRPS/CRPSS + Brier/BSS on the app's
    thresholds, from the 11-member ensemble -- so EC46's odds can be compared to GEFS's.

Caveat: EC46 is a different sample/resolution than the GEFS/CFSv2 backtest (2004-20 @
1.5 deg vs 2021-25 @ 0.25-0.5 deg), so compare skill *levels* vs each model's own
climatology baseline, not case-by-case.

    python backtest/ec46_backtest.py --truth-only     # build+cache truth, then stop
    python backtest/ec46_backtest.py                  # score (det + prob if members present)
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
FC = HERE.parent
sys.path.insert(0, str(FC))
sys.path.insert(0, str(HERE))
os.environ.setdefault("GRAM_GEO", "lgd")

from config import DATA_DIR                                              # noqa: E402
from forecast_region import gadm_districts                              # noqa: E402
from forecast_region_s2s import (anomalise, model_clim, _lonlat,        # noqa: E402
                                 WET_MM, DRY_MM, HEAVY_MM, DRYSPELL_MM, HOT_C)
from build_truth import (build_climatology, build_temp_clim, year_current,  # noqa: E402
                         weekly_anom, weight_tensor)
from metrics import crps_ensemble                                       # noqa: E402

EC46_DIR = DATA_DIR / "ec46"
TRUTH = HERE / "truth_ec46"
SCORES = HERE / "scores"
TRUTH.mkdir(exist_ok=True); SCORES.mkdir(exist_ok=True)
DISTRICTS_CSV = FC.parent / "data" / "district_coordinates.csv"
HYEARS = list(range(2004, 2021))
WEEKS = 5
EVENTS = [("wetter", "precip", "ge", WET_MM), ("drier", "precip", "le", DRY_MM),
          ("heavy", "precip", "ge", HEAVY_MM), ("dryspell", "precip", "le", DRYSPELL_MM),
          ("hot", "t2m", "ge", HOT_C)]


def _collapse_valid(W, field, latn, lonn):
    valid = xr.where(field.notnull(), 1.0, 0.0)
    num = xr.dot(W, field.fillna(0.0), dims=[latn, lonn])
    den = xr.dot(W, valid, dims=[latn, lonn])
    return num / den.where(den > 0)


def build_truth_cache(districts, gadm):
    """Cache obs district weekly anomalies per (hyear, mmdd) to truth_ec46/<hyear>_<mmdd>.nc."""
    mmdds = sorted({f.name.split("_")[1] for f in EC46_DIR.glob("ec46rf_*_india_weekly.nc")})
    need = [(hy, md) for hy in HYEARS for md in mmdds
            if not (TRUTH / f"{hy}_{md}.nc").exists()]
    if not need:
        print(f"truth cached for all {len(HYEARS)}x{len(mmdds)} (hyear, date)")
        return
    print(f"building IMD normals + truth for {len(need)} (hyear, date) ...")
    rain_clim, temp_clim = build_climatology((1991, 2020)), build_temp_clim((1991, 2020))
    wcache = {}
    for hy in HYEARS:
        todo = [md for (h, md) in need if h == hy]
        if not todo:
            continue
        print(f"[{hy}] IMD obs ({len(todo)} dates) ...", flush=True)
        fields = {"precip": (year_current(hy, "rain"), rain_clim),
                  "t2m": (year_current(hy, "temp"), temp_clim)}
        for md in todo:
            init_ts = pd.Timestamp(f"{hy}-{md[:2]}-{md[2:]}")
            dvars = {}
            for var, (cur, clim) in fields.items():
                anom = weekly_anom(cur, clim, init_ts, WEEKS)
                if anom is None:
                    continue
                lonn, latn = _lonlat(cur)
                key = (latn, lonn, cur[latn].size, cur[lonn].size)
                if key not in wcache:
                    W, la, lo = weight_tensor(cur.isel(time=0), districts, gadm)
                    wcache[key] = (W, la, lo)
                W, la, lo = wcache[key]
                dvars[f"obs_{var}_anom"] = _collapse_valid(W, anom, la, lo).transpose("district", "week")
            if dvars:
                xr.Dataset(dvars).to_netcdf(TRUTH / f"{hy}_{md}.nc")


def collapse_forecast(districts, gadm):
    """Per (mmdd, hyear): EC46 anomalies collapsed to districts. Uses members if present
    (returns members) else control. Returns dict[(mmdd, hyear, var)] -> (member?, district, week)."""
    era5 = xr.open_dataset(DATA_DIR / "clim" / "era5_weekly_init0711_india_weekly.nc")
    mem_files = {f.name.split("_")[1]: f for f in EC46_DIR.glob("ec46rfm_*_members.nc")}
    ctl_files = {f.name.split("_")[1]: f for f in EC46_DIR.glob("ec46rf_*_india_weekly.nc")}
    use_members = len(mem_files) == len(ctl_files) and mem_files
    print(f"forecast side: {'11-member ensemble' if use_members else 'control only'} "
          f"({len(mem_files)} member files, {len(ctl_files)} control files)")
    files = mem_files if use_members else ctl_files
    W = None
    out = {}
    for md, f in sorted(files.items()):
        ds = xr.open_dataset(f)
        ds = ds.sel(hyear=[h for h in HYEARS if h in ds.hyear.values])
        clim, _ = model_clim("EC46", f"2024-{md[:2]}-{md[2:]}", era5)
        for var in ("t2m", "precip"):
            a = anomalise(ds[var], clim[var])
            lonn, latn = _lonlat(a)
            if W is None:
                ref = a.isel({d: 0 for d in a.dims if d not in (latn, lonn)})
                W, _la, _lo = weight_tensor(ref, districts, gadm)
            coll = xr.dot(W, a, dims=[_la, _lo])        # (..., district, ...) member/hyear/week kept
            for h in ds.hyear.values:
                out[(md, int(h), var)] = coll.sel(hyear=int(h))
        ds.close()
    return out, use_members


def score(fc, use_members):
    """Join forecast + cached truth -> long frame, then det (+ prob) scores by lead."""
    det_rows, prob_rows = [], []
    for (md, hy, var), da in fc.items():
        tp = TRUTH / f"{hy}_{md}.nc"
        if not tp.exists():
            continue
        tr = xr.open_dataset(tp)
        oname = f"obs_{var}_anom"
        if oname not in tr:
            tr.close(); continue
        obs = tr[oname].transpose("district", "week")
        if use_members:
            mem = da.transpose("district", "number", "week").values     # (D, M, W)
            emean = np.nanmean(mem, axis=1)
        else:
            emean = da.transpose("district", "week").values             # (D, W)
        for wi, wk in enumerate(obs["week"].values):
            o = obs.isel(week=wi).values
            fm = emean[:, wi]
            ok = np.isfinite(o) & np.isfinite(fm)
            for di in np.where(ok)[0]:
                det_rows.append((int(wk), var, fm[di], o[di]))
            if use_members:
                M = mem[:, :, wi]
                for di in np.where(ok)[0]:
                    prob_rows.append((int(wk), var, M[di], o[di]))
        tr.close()

    det = pd.DataFrame(det_rows, columns=["week", "variable", "fc", "obs"])
    out = []
    for var in ("precip", "t2m"):
        for wk in range(1, WEEKS + 1):
            g = det[(det.variable == var) & (det.week == wk)]
            f_, o = g["fc"].to_numpy(), g["obs"].to_numpy()
            if f_.size < 3:
                continue
            rmse = float(np.sqrt(np.mean((f_ - o) ** 2)))
            rc = float(np.sqrt(np.mean(o ** 2)))
            out.append(dict(model="ec46", variable=var, week=wk, n=int(f_.size),
                            acc=float(np.corrcoef(f_, o)[0, 1]) if f_.std() and o.std() else np.nan,
                            rmse=rmse, rmsess=float(1 - rmse / rc) if rc > 0 else np.nan,
                            bias=float(np.mean(f_ - o))))
    det_df = pd.DataFrame(out)
    det_df.to_csv(SCORES / "ec46_deterministic.csv", index=False)

    prob_df = None
    if prob_rows:
        pr = pd.DataFrame(prob_rows, columns=["week", "variable", "members", "obs"])
        rows = []
        for var in ("precip", "t2m"):
            for wk in range(1, WEEKS + 1):
                g = pr[(pr.variable == var) & (pr.week == wk)]
                if len(g) < 20:
                    continue
                M = np.vstack(g["members"].to_numpy())
                o = g["obs"].to_numpy()
                crps = crps_ensemble(M, o)
                cc = np.abs(o)
                rec = dict(model="ec46", variable=var, week=wk, n=len(g),
                           crps=float(np.nanmean(crps)),
                           crpss=float(1 - np.nanmean(crps) / np.nanmean(cc)) if np.nanmean(cc) > 0 else np.nan)
                for name, evar, cmp, lvl in EVENTS:
                    if evar != var:
                        continue
                    p = (M >= lvl).mean(1) if cmp == "ge" else (M <= lvl).mean(1)
                    y = (o >= lvl if cmp == "ge" else o <= lvl).astype(float)
                    base = y.mean()
                    bs, bsc = np.mean((p - y) ** 2), np.mean((base - y) ** 2)
                    rec[f"bss_{name}"] = float(1 - bs / bsc) if bsc > 0 else np.nan
                rows.append(rec)
        prob_df = pd.DataFrame(rows)
        prob_df.to_csv(SCORES / "ec46_probabilistic.csv", index=False)
    return det_df, prob_df


def main():
    ap = argparse.ArgumentParser(description="EC46 skill backtest vs IMD.")
    ap.add_argument("--truth-only", action="store_true", help="Build+cache truth, then stop.")
    args = ap.parse_args()
    districts = pd.read_csv(DISTRICTS_CSV)
    gadm = gadm_districts()
    build_truth_cache(districts, gadm)
    if args.truth_only:
        print("truth cache ready.")
        return
    fc, use_members = collapse_forecast(districts, gadm)
    det, prob = score(fc, use_members)
    with pd.option_context("display.width", 200):
        print("\n=== EC46 deterministic skill by lead (2004-2020) ===")
        print(det.round(3).to_string(index=False))
        if prob is not None:
            print("\n=== EC46 probabilistic skill by lead (11-member ensemble) ===")
            print(prob.round(3).to_string(index=False))
    print(f"\nwrote -> {SCORES}")


if __name__ == "__main__":
    main()
