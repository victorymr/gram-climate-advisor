#!/usr/bin/env python3
"""
Download ECMWF extended-range (EC46, 46-day) subseasonal forecasts from the
ECMWF Data Store (ECDS) dataset 's2s-forecasts', crop to India, aggregate to
weekly means, save NetCDF (t2m degC, precip mm/day; dims week,lat,lon).

Why ECDS: the anonymous open-data ENS stops at 15 days; the 46-day extended
ensemble lives in S2S, which migrated to https://ecds.ecmwf.int (cdsapi).
EMBARGO: S2S real-time has a ~3-week delay; use a matched older init for both
models. Reforecasts have no embargo.

KEY SCHEMA FACTS (from the ECDS s2s-forecasts form):
  * variable names use underscores: '2_m_temperature', 'total_precipitation'.
  * '2_m_temperature' is a DAILY-AVERAGED variable -> leadtime_hour are 24h
    WINDOWS like '0_24','24_48',...  (one value per forecast day).
  * 'total_precipitation' is ACCUMULATED-since-init (kg m^-2 = mm) -> leadtime_hour single
    hours '0','168','336',...  (we only need the weekly boundaries).
  -> temperature and precip therefore need SEPARATE requests.
  * data_format is GRIB only (open with cfgrib).
  * forecast_type: 'perturbed_forecast' (all members) or 'control_forecast'.

SETUP
-----
1. ECDS account (same ECMWF login as the Climate CDS); accept the s2s-forecasts
   (and s2s-reforecasts) licence on the dataset page.
2. ~/.ecdsapirc  ->  url: https://ecds.ecmwf.int/api   key: <token>
   (or env ECDS_URL / ECDS_KEY). Keep ~/.cdsapirc as-is for SEAS5.
3. pip install "cdsapi>=0.7.7" cfgrib eccodes xarray netcdf4

USAGE
-----
    python download_ec46.py --date 2026-05-24 --inspect      # tiny 1-field probe, print structure
    python download_ec46.py --date 2026-05-24                # forecast -> weekly India NetCDF
    python download_ec46.py --date 2026-05-24 --reforecast   # matching reforecast climatology
"""

import os
import sys
import argparse
from pathlib import Path

import cdsapi
import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR, INDIA_BBOX, cds_area
from utils import subset_to_india, save_netcdf

EC46_DIR = DATA_DIR / "ec46"
EC46_DIR.mkdir(parents=True, exist_ok=True)

DATASET = "s2s-forecasts"
DATASET_RFC = "s2s-reforecasts"
MAX_DAYS = 46                       # EC46 horizon
VAR_T = "2_m_temperature"           # daily-averaged
VAR_P = "total_precipitation"       # accumulated since init (kg m^-2 = mm)


def ecds_client():
    url, key = os.environ.get("ECDS_URL"), os.environ.get("ECDS_KEY")
    rc = Path.home() / ".ecdsapirc"
    if not (url and key) and rc.exists():
        kv = dict(l.split(":", 1) for l in rc.read_text().splitlines() if ":" in l)
        url, key = kv.get("url", "").strip(), kv.get("key", "").strip()
    if not (url and key):
        sys.exit("No ECDS credentials. Create ~/.ecdsapirc (url: https://ecds.ecmwf.int/api / "
                 "key: <token>) or set ECDS_URL/ECDS_KEY.")
    return cdsapi.Client(url=url, key=key)


def daily_windows(max_days):
    """Daily-averaged leadtime_hour windows: '0_24','24_48',... up to max_days."""
    return [f"{d*24}_{d*24+24}" for d in range(max_days)]


def week_boundaries(max_days):
    """Single-hour leads at week edges 0,168,336,... within the horizon."""
    n_weeks = (max_days * 24) // 168
    return [str(w * 168) for w in range(n_weeks + 1)], n_weeks


def base_request(date, reforecast):
    d = pd.Timestamp(date)
    req = {
        "origin": "ecmwf",
        "forecast_type": "perturbed_forecast",
        "level_type": "single_level",
        "year": [f"{d.year}"], "month": [f"{d.month:02d}"], "day": [f"{d.day:02d}"],
        "time": ["00:00"],
        "data_format": "grib",
        "area": cds_area(INDIA_BBOX),          # [N, W, S, E]
    }
    if reforecast:
        req["reforecast_year"] = [str(y) for y in range(d.year - 20, d.year)]
    return req


def retrieve(date, reforecast, tag, kind, inspect=False):
    """Download temp + precip GRIBs; return (temp_path, precip_path)."""
    ds_name = DATASET_RFC if reforecast else DATASET
    cli = ecds_client()
    traw = EC46_DIR / f"ec46_{tag}_{kind}_t.grib"
    praw = EC46_DIR / f"ec46_{tag}_{kind}_p.grib"

    treq = base_request(date, reforecast)
    treq["variable"] = [VAR_T]
    treq["leadtime_hour"] = ["0_24"] if inspect else daily_windows(MAX_DAYS)
    if inspect:
        treq["forecast_type"] = "control_forecast"
    print(f"Requesting {ds_name} {VAR_T} (daily-averaged) init {date} ...")
    cli.retrieve(ds_name, treq, str(traw))
    if inspect:
        return traw, None

    preq = base_request(date, reforecast)
    preq["variable"] = [VAR_P]
    preq["leadtime_hour"], _ = week_boundaries(MAX_DAYS)
    print(f"Requesting {ds_name} {VAR_P} (accumulated, week boundaries) init {date} ...")
    cli.retrieve(ds_name, preq, str(praw))
    return traw, praw


def _open(grib):
    return xr.open_dataset(grib, engine="cfgrib")


def _pick(ds, *names):
    return next((n for n in names if n in ds.data_vars), None)


def _ens_mean(da):
    dims = [d for d in ("number", "reforecast_year", "hdate") if d in da.dims]
    return da.mean(dims) if dims else da


def _step_hours(ds, dim):
    s = ds[dim]
    if np.issubdtype(np.asarray(s).dtype, np.timedelta64):
        return (s / np.timedelta64(1, "h")).astype(int).values
    return np.asarray(s).astype(int)


def process(tpath, ppath, out_path, init_date, reforecast):
    from s2s_utils import to_weekly
    # ---- temperature: daily means -> weekly mean (K -> degC) ----
    dt = subset_to_india(_open(tpath), INDIA_BBOX)
    tvar = _pick(dt, "t2m", "2t", "t2m_mean")
    t = _ens_mean(dt[tvar])
    sdim = [d for d in t.dims if d not in ("latitude", "longitude", "lat", "lon")]
    sdim = sdim[0] if sdim else "step"
    t = t.sortby(sdim)
    # requested as consecutive 24h windows, so day index = order (1..N) -> end hours
    lead_h = (np.arange(t.sizes[sdim]) + 1) * 24
    t = t.assign_coords(lead_hours=(sdim, lead_h))
    t2m = to_weekly(t, method="mean") - 273.15

    # ---- precip: accumulated tp (m) differenced across week boundaries -> mm/day ----
    dp = subset_to_india(_open(ppath), INDIA_BBOX)
    pvar = _pick(dp, "tp", "tprate", "total_precipitation")
    p = _ens_mean(dp[pvar])
    pdim = [d for d in p.dims if d not in ("latitude", "longitude", "lat", "lon")]
    pdim = pdim[0] if pdim else "step"
    p = p.assign_coords(lead_hours=(pdim, _step_hours(dp, pdim))).sortby("lead_hours")
    weeks = [int(w) for w in t2m["week"].values]
    pw = []
    for w in weeks:
        hi, lo = w * 168, (w - 1) * 168
        if hi not in p["lead_hours"].values:
            continue
        end = p.sel({pdim: p["lead_hours"] == hi}).squeeze(pdim, drop=True)
        start = (p.sel({pdim: p["lead_hours"] == lo}).squeeze(pdim, drop=True)
                 if lo in p["lead_hours"].values else xr.zeros_like(end))
        pw.append(((end - start) / 7.0).assign_coords(week=w))   # tp is kg m^-2 = mm; weekly accum -> mm/day
    precip = xr.concat(pw, dim="week")
    precip = precip.reindex(week=t2m["week"])   # align weeks with temperature

    out = xr.Dataset({"t2m": t2m, "precip": precip},
                     attrs={"model": "EC46",
                            "init_date": pd.Timestamp(init_date).strftime("%Y%m%d"),
                            "kind": "climatology" if reforecast else "forecast",
                            "source": "ECMWF ECDS s2s-forecasts"})
    save_netcdf(out, out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Download EC46 (ECMWF extended) for India, weekly NetCDF.")
    ap.add_argument("--date", required=True, help="Init date YYYY-MM-DD (mind the ~3-week embargo).")
    ap.add_argument("--reforecast", action="store_true", help="Fetch matching reforecast climatology.")
    ap.add_argument("--inspect", action="store_true", help="Tiny 1-field probe; print structure; stop.")
    ap.add_argument("--reprocess", action="store_true", help="Skip download; reprocess existing GRIBs.")
    args = ap.parse_args()

    d = pd.Timestamp(args.date)
    tag = d.strftime("%Y%m%d")
    kind = "clim" if args.reforecast else "fc"
    out = (EC46_DIR / f"ec46_clim_init{d.strftime('%m%d')}_india_weekly.nc" if args.reforecast
           else EC46_DIR / f"ec46_{tag}_india_weekly.nc")
    tpath = EC46_DIR / f"ec46_{tag}_{kind}_t.grib"
    ppath = EC46_DIR / f"ec46_{tag}_{kind}_p.grib"

    if not args.reprocess:
        tpath, ppath = retrieve(args.date, args.reforecast, tag, kind, inspect=args.inspect)

    if args.inspect:
        ds = _open(tpath)
        print(ds)
        print("\nData vars:", list(ds.data_vars), "\nDims:", dict(ds.sizes))
        print("\nIf the temperature var isn't 't2m', tell me and I'll adjust _pick().")
        return

    process(tpath, ppath, out, args.date, args.reforecast)
    print(f"Done -> {out}")


if __name__ == "__main__":
    main()
