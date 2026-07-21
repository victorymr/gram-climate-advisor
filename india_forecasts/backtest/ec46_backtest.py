#!/usr/bin/env python3
"""
Backtest EC46 (ECMWF extended-range) deterministic skill against IMD observations, to put
a measured number on EC46's weight in the multi-model mean instead of assuming 1.0.

Uses the S2S reforecasts saved by download_ec46_reforecast.py: 21 monsoon cycle dates,
each with 20 hindcast years (control forecast). We score hindcast years 2004-2020 (IMD
obs already cached). EC46 is anomalised vs its own reforecast climatology (data/clim/
ec46_model_clim.nc) exactly as the live pipeline does; obs are IMD weekly district
anomalies vs the 1991-2020 day-of-year normal (same construction as build_truth.py).

EC46 reforecasts are CONTROL only (1 member), so this is deterministic skill
(ACC / RMSE / RMSESS / bias) -- which is what sets the MME weight. It prints EC46 by lead
next to the GEFS/CFSv2 numbers from the main backtest for context.

Caveats: different sample from the GEFS/CFSv2 backtest (EC46 = 2004-2020 monsoon reforecast
dates at 1.5 deg; GEFS/CFSv2 = 2021-2025 at 0.25-0.5 deg), so compare skill *levels* vs
each model's own climatology baseline, not case-by-case.

    python backtest/ec46_backtest.py
"""

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
from forecast_region_s2s import anomalise, model_clim, _lonlat          # noqa: E402
from build_truth import (build_climatology, build_temp_clim, year_current,  # noqa: E402
                         weekly_anom, weight_tensor)

EC46_DIR = DATA_DIR / "ec46"
SCORES = HERE / "scores"
SCORES.mkdir(exist_ok=True)
DISTRICTS_CSV = FC.parent / "data" / "district_coordinates.csv"
HYEARS = list(range(2004, 2021))          # 2004-2020: IMD obs cached
WEEKS = 5


def collapse_valid(W, field, latn, lonn):
    """Valid-cell weighted mean: sum(W*x)/sum(W*isfinite(x)) -> renormalises onto land."""
    valid = xr.where(field.notnull(), 1.0, 0.0)
    num = xr.dot(W, field.fillna(0.0), dims=[latn, lonn])
    den = xr.dot(W, valid, dims=[latn, lonn])
    return num / den.where(den > 0)


def main():
    districts = pd.read_csv(DISTRICTS_CSV)
    gadm = gadm_districts()
    era5 = xr.open_dataset(DATA_DIR / "clim" / "era5_weekly_init0711_india_weekly.nc")

    # --- EC46 forecast side: anomalise each reforecast vs EC46 own clim, collapse ---
    files = sorted(EC46_DIR.glob("ec46rf_*_india_weekly.nc"))
    if not files:
        sys.exit("No EC46 reforecast files; run download_ec46_reforecast.py first.")
    print(f"EC46 reforecast dates: {len(files)}, hindcast years {HYEARS[0]}-{HYEARS[-1]}")

    # weight tensor on the EC46 1.5deg grid (built once)
    ec_w = None
    fc_rows = []
    for f in files:
        mmdd = f.name.split("_")[1]
        ds = xr.open_dataset(f)
        ds = ds.sel(hyear=[h for h in HYEARS if h in ds.hyear.values])
        cyc = f"2024-{mmdd[:2]}-{mmdd[2:]}"
        clim, label = model_clim("EC46", cyc, era5)     # ec46 own clim at this DOY
        for var in ("t2m", "precip"):
            a = anomalise(ds[var], clim[var])            # (hyear, week, lat, lon)
            lonn, latn = _lonlat(a)
            if ec_w is None:
                ec_w, _la, _lo = weight_tensor(a.isel(hyear=0, week=0), districts, gadm)
            coll = xr.dot(ec_w, a, dims=[_la, _lo])      # (district, hyear, week)
            for h in ds.hyear.values:
                arr = coll.sel(hyear=int(h)).transpose("district", "week").values
                for wi, wk in enumerate(a["week"].values):
                    fc_rows.append((mmdd, int(h), int(wk), var, arr[:, wi]))
        ds.close()

    fc = {}
    for mmdd, h, wk, var, arr in fc_rows:
        fc[(mmdd, h, wk, var)] = arr

    # --- truth side: IMD obs weekly district anomaly for each (mmdd, hyear) valid week ---
    print("building IMD normals ...")
    rain_clim = build_climatology((1991, 2020))
    temp_clim = build_temp_clim((1991, 2020))
    state = districts["state"].to_numpy()
    dist = districts["district"].to_numpy()

    truth_wcache = {}
    rows = []
    mmdds = sorted({f.name.split("_")[1] for f in files})
    for hy in HYEARS:
        print(f"[{hy}] IMD obs ...", flush=True)
        fields = {"precip": (year_current(hy, "rain"), rain_clim),
                  "t2m": (year_current(hy, "temp"), temp_clim)}
        for mmdd in mmdds:
            init_ts = pd.Timestamp(f"{hy}-{mmdd[:2]}-{mmdd[2:]}")
            for var, (cur, clim) in fields.items():
                if (mmdd, hy, 1, var) not in fc:
                    continue
                anom = weekly_anom(cur, clim, init_ts, WEEKS)
                if anom is None:
                    continue
                lonn, latn = _lonlat(cur)
                key = (latn, lonn, cur[latn].size, cur[lonn].size)
                if key not in truth_wcache:
                    W, la, lo = weight_tensor(cur.isel(time=0), districts, gadm)
                    truth_wcache[key] = (W, la, lo)
                W, la, lo = truth_wcache[key]
                ob = collapse_valid(W, anom, la, lo).transpose("district", "week")
                for wi, wk in enumerate(anom["week"].values):
                    key2 = (mmdd, hy, int(wk), var)
                    if key2 not in fc:
                        continue
                    o = ob.isel(week=wi).values
                    f_ = fc[key2]
                    m = np.isfinite(o) & np.isfinite(f_)
                    for di in np.where(m)[0]:
                        rows.append((int(wk), var, float(f_[di]), float(o[di])))

    df = pd.DataFrame(rows, columns=["week", "variable", "ec46", "obs"])
    print(f"\nscored {len(df):,} district-week samples")

    # deterministic skill by lead
    out = []
    for var in ("precip", "t2m"):
        for wk in range(1, WEEKS + 1):
            g = df[(df.variable == var) & (df.week == wk)]
            f_, o = g["ec46"].to_numpy(), g["obs"].to_numpy()
            if f_.size < 3:
                continue
            rmse = float(np.sqrt(np.mean((f_ - o) ** 2)))
            rmse_clim = float(np.sqrt(np.mean(o ** 2)))
            out.append(dict(variable=var, week=wk, n=int(f_.size),
                            acc=float(np.corrcoef(f_, o)[0, 1]) if f_.std() > 0 and o.std() > 0 else np.nan,
                            rmse=rmse,
                            rmsess=float(1 - rmse / rmse_clim) if rmse_clim > 0 else np.nan,
                            bias=float(np.mean(f_ - o))))
    res = pd.DataFrame(out)
    res.to_csv(SCORES / "ec46_deterministic.csv", index=False)
    with pd.option_context("display.width", 200):
        print("\n=== EC46 deterministic skill by lead (2004-2020 monsoon reforecasts) ===")
        print(res.round(3).to_string(index=False))

    # context: GEFS/CFSv2 from the main (own-referenced) backtest
    ref = SCORES / "deterministic_ownref.csv"
    if ref.exists():
        d = pd.read_csv(ref)
        piv = d[d.model.isin(["gefs", "cfsv2"])].pivot_table(
            index=["variable", "week"], columns="model", values=["acc", "rmsess"])
        print("\n=== For context: GEFS / CFSv2 ACC & RMSESS (2021-2025 backtest) ===")
        print(piv.round(3).to_string())
    print(f"\nwrote -> {SCORES/'ec46_deterministic.csv'}")


if __name__ == "__main__":
    main()
