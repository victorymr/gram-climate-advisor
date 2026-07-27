#!/usr/bin/env python3
"""
Build a common ERA5 climatology over India for anomaly maps in plot_s2s_multi.py.

Two stages:
  1. DAY-OF-YEAR climatology (init-independent, built once). Downloads ERA5 daily
     2 m temperature (daily mean) and total precipitation (daily sum) over India
     for a reference period (default 1991-2020) from the Copernicus CDS dataset
     'derived-era5-single-levels-daily-statistics', then averages by day-of-year
     and lightly smooths. Saved to data/clim/era5_doy_clim_india.nc
     (vars t2m [degC], precip [mm/day]; dims dayofyear, latitude, longitude).
  2. PER-INIT weekly climatology. For a forecast --date, averages the DOY clim
     over each week's valid calendar days -> data/clim/era5_weekly_init<MMDD>_india_weekly.nc
     (vars t2m, precip; dims week, latitude, longitude). Feed this to
     plot_s2s_multi.py --common-clim so EVERY model is anomalised the same way.

Uses your existing Climate-CDS ~/.cdsapirc (the SEAS5 one) -- no new account.
Accept the dataset licence once on its CDS page.

SETUP : pip install "cdsapi>=0.7" xarray netcdf4 scipy
USAGE
-----
    python build_era5_clim.py --date 2026-06-29                  # build DOY (if missing) + weekly for this init
    python build_era5_clim.py --build-doy --years 1991 2020      # (re)build the DOY clim only
    python build_era5_clim.py --date 2026-06-29 --weeks 6
"""

import sys
import zipfile
import argparse
from pathlib import Path

import cdsapi
import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX, cds_area
from utils import subset_to_india, save_netcdf
from s2s_utils import weekly_clim_for_init

CLIM_DIR = DATA_DIR / "clim"
CLIM_DIR.mkdir(parents=True, exist_ok=True)
DOY_PATH = CLIM_DIR / "era5_doy_clim_india.nc"
DATASET = "derived-era5-single-levels-daily-statistics"

MONTHS = [f"{m:02d}" for m in range(1, 13)]
DAYS = [f"{d:02d}" for d in range(1, 32)]


def _request(variable, statistic, year):
    return {
        "product_type": "reanalysis",
        "variable": [variable],
        "year": [str(year)],
        "month": MONTHS,
        "day": DAYS,
        "daily_statistic": statistic,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": cds_area(INDIA_BBOX),          # [N, W, S, E]
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def _open_any(path):
    """Open a CDS download that may be NetCDF or a zip-of-NetCDF."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            ncs = [n for n in z.namelist() if n.endswith(".nc")]
            z.extractall(path.parent)
            path = path.parent / ncs[0]
    return xr.open_dataset(path)


def _pick(ds, *names):
    return next((n for n in names if n in ds.data_vars), list(ds.data_vars)[0])


def build_doy(years):
    cli = cdsapi.Client()
    raw = CLIM_DIR / "_era5_raw"
    raw.mkdir(exist_ok=True)
    t_years, p_years = [], []
    for y in range(years[0], years[1] + 1):
        tf, pf = raw / f"t2m_{y}.nc", raw / f"tp_{y}.nc"
        if not tf.exists():
            print(f"  {y}: 2m_temperature (daily_mean) ...")
            cli.retrieve(DATASET, _request("2m_temperature", "daily_mean", y), str(tf))
        if not pf.exists():
            print(f"  {y}: total_precipitation (daily_sum) ...")
            cli.retrieve(DATASET, _request("total_precipitation", "daily_sum", y), str(pf))
        dt = subset_to_india(_open_any(tf), INDIA_BBOX)
        dp = subset_to_india(_open_any(pf), INDIA_BBOX)
        t_years.append(dt[_pick(dt, "t2m", "2t", "2m_temperature")] - 273.15)     # K -> degC
        p_years.append(dp[_pick(dp, "tp", "total_precipitation")] * 1000.0)       # m/day -> mm/day

    t = xr.concat(t_years, dim="valid_time" if "valid_time" in t_years[0].dims else "time")
    p = xr.concat(p_years, dim=t.dims[0])
    tdim = t.dims[0]
    t = t.rename({tdim: "time"}) if tdim != "time" else t
    p = p.rename({p.dims[0]: "time"}) if p.dims[0] != "time" else p

    # day-of-year climatology, then a 15-day periodic smoother
    def doy_clim(da):
        c = da.groupby("time.dayofyear").mean("time")
        c = c.reindex(dayofyear=np.arange(1, 367)).interpolate_na("dayofyear", period=366)
        pad = c.pad(dayofyear=15, mode="wrap")
        return pad.rolling(dayofyear=15, center=True, min_periods=1).mean().isel(
            dayofyear=slice(15, 15 + c.sizes["dayofyear"]))

    ds = xr.Dataset({"t2m": doy_clim(t), "precip": doy_clim(p)},
                    attrs={"source": "ERA5 daily-statistics via CDS",
                           "ref_years": f"{years[0]}-{years[1]}"})
    save_netcdf(ds, DOY_PATH)
    print(f"DOY climatology -> {DOY_PATH}")
    return ds


def main():
    ap = argparse.ArgumentParser(description="Build ERA5 common climatology for India anomaly maps.")
    ap.add_argument("--date", default=None, help="Forecast init YYYY-MM-DD (build the per-init weekly clim).")
    ap.add_argument("--weeks", type=int, default=6, help="Number of forecast weeks (default 6).")
    ap.add_argument("--years", type=int, nargs=2, metavar=("START", "END"), default=[1991, 2020])
    ap.add_argument("--build-doy", action="store_true", help="(Re)build the day-of-year climatology and stop.")
    args = ap.parse_args()

    if args.build_doy or not DOY_PATH.exists():
        if not DOY_PATH.exists():
            print(f"DOY climatology not found; building {args.years[0]}-{args.years[1]} "
                  f"(first build downloads ERA5 and can take a while) ...")
        doy = build_doy(args.years)
        if args.build_doy:
            return
    else:
        doy = xr.open_dataset(DOY_PATH)

    if not args.date:
        print("DOY climatology ready. Re-run with --date YYYY-MM-DD to make a per-init weekly clim.")
        return

    weeks = list(range(1, args.weeks + 1))
    wk = weekly_clim_for_init(doy, args.date, weeks)
    d = pd.Timestamp(args.date)
    out = CLIM_DIR / f"era5_weekly_init{d.strftime('%m%d')}_india_weekly.nc"
    wk.attrs.update(source="ERA5 DOY clim -> per-init weekly", init_date=d.strftime("%Y%m%d"))
    save_netcdf(wk, out)
    print(f"Per-init weekly clim -> {out}\n"
          f"Use it:  python plot_s2s_multi.py --auto --common-clim {out}")


if __name__ == "__main__":
    main()
