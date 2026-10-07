#!/usr/bin/env python3
"""
Observed rainfall departures per district from IMD 0.25 deg gridded daily rainfall.

For each advisor district, compare observed accumulated rainfall this season against the
IMD day-of-year climatology and report:
  - rainfall_since_june_1_pct_departure
  - rainfall_last_7_days_pct_departure
  - rainfall_last_14_days_pct_departure
  - monsoon_onset_status   (a simple proxy from the season-to-date departure)
Writes plots/observed_departures.csv, which the advisor bridge (import_model_forecasts.py)
merges into district_forecasts.json — this is what lets the drought / delayed-monsoon /
dry-spell scenarios fire nationwide (they key on observed rainfall departures).

Data source: India Meteorological Department 0.25 deg gauge-based gridded rainfall via imdlib.
  - current season : IMD real-time daily grids (provisional, ~1-2 day lag), fetched with
                     retries + a per-day cache in data/obs/imd_rt, read via imdlib.open_real_data
  - climatology    : imdlib.get_data       (historical yearwise) -> day-of-year normal, cached
Both are the same IMD product/grid, so the departure is internally consistent. IMD is the
gauge reference over India (see Pai et al. 2014); ERA5 runs ~15% wet, CHIRPS is a satellite-
primary alternative.

Usage (heavy/global Python; imdlib downloads from IMD Pune):
    python observed_departures.py                          # current year, Jun 1 -> latest
    python observed_departures.py --year 2026 --asof 2026-07-04
    python observed_departures.py --clim-years 1991 2020   # (re)build the IMD normal
"""

import sys
import csv
import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config import DATA_DIR
from forecast_region import gadm_districts, region_weights
from forecast_region_s2s import resolve_geom, _lonlat, PLOTS_DIR, DEFAULT_DISTRICTS

IMD_DIR = DATA_DIR / "obs" / "imd"
RT_DIR = DATA_DIR / "obs" / "imd_rt"
FIELDS = ["state", "district", "rainfall_since_june_1_pct_departure",
          "rainfall_last_7_days_pct_departure", "rainfall_last_14_days_pct_departure",
          "monsoon_onset_status", "obs_asof"]


def _rain(ds):
    """IMD 'rain' DataArray with -999 fill masked to NaN (ocean/no-data)."""
    return ds["rain"].where(ds["rain"] >= 0)


def build_climatology(years):
    """IMD day-of-year rainfall normal (mm/day) over `years`, cached to NetCDF."""
    import imdlib as imd
    cache = IMD_DIR / f"imd_rain_doy_clim_{years[0]}_{years[1]}.nc"
    if cache.exists():
        return xr.open_dataset(cache)["clim"]
    IMD_DIR.mkdir(parents=True, exist_ok=True)
    das = []
    for y in range(years[0], years[1] + 1):
        print(f"  IMD historical rain {y} ...")
        das.append(_rain(imd.get_data("rain", y, y, fn_format="yearwise", file_dir=str(IMD_DIR)).get_xarray()))
    allr = xr.concat(das, dim="time")
    clim = allr.groupby("time.dayofyear").mean("time").rename("clim")
    clim.to_dataset().to_netcdf(cache)
    print(f"  cached climatology -> {cache}")
    return clim


RT_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"   # imdlib's real-time endpoint
RT_BYTES = 129 * 135 * 4     # one complete 0.25 deg daily grid (float32)
RT_REFRESH_DAYS = 7          # re-fetch the newest week every run: IMD revises provisional data
RT_MAX_SHORTFALL = 7         # newest days allowed to be not-yet-published before we give up
RT_THREADS = 2               # imdpune.gov.in takes ~6-10 s per day and stalls under load


def _rt_path(day):
    return RT_DIR / f"rain_ind0.25_{day:%y_%m_%d}.grd"     # imdlib's naming, so open_real_data reads it


def _rt_cached(day):
    p = _rt_path(day)
    return p.exists() and p.stat().st_size == RT_BYTES


def _fetch_rt_day(sess, day, attempts=5):
    """Download one IMD real-time daily grid into the cache; True on success. Unlike
    imdlib.get_real_data (no timeout, no retry, aborts the season on the first error),
    a stalled or failed request here is retried and only costs that one day. The backoff
    (5+10+20+40 s) rides out the minute-long outages imdpune.gov.in has (seen 2026-10-06)."""
    import time
    import requests
    path = _rt_path(day)
    for i in range(attempts):
        try:
            r = sess.post(RT_URL, data={"rain": f"{day:%d%m%Y}"}, timeout=(15, 90))
            r.raise_for_status()
            if len(r.content) == RT_BYTES:      # anything else: not published yet / error page
                tmp = path.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(path)
                return True
        except requests.RequestException:
            pass
        if i < attempts - 1:
            time.sleep(5 * 2 ** i)
    return False


def get_current(year, asof):
    """IMD real-time daily rain (mm/day), Jun 1 -> asof, on the IMD grid.

    Returns (rain, end): days already cached are kept (only missing days and the newest
    RT_REFRESH_DAYS are fetched), and `end` may fall short of asof by up to
    RT_MAX_SHORTFALL days if IMD has not published the newest days yet."""
    import imdlib as imd
    import requests
    from concurrent.futures import ThreadPoolExecutor
    RT_DIR.mkdir(parents=True, exist_ok=True)
    days = list(pd.date_range(f"{year}-06-01", asof).date)
    todo = [d for d in days if not _rt_cached(d) or (asof - d).days < RT_REFRESH_DAYS]
    print(f"  IMD real-time rain: {len(days) - len(todo)} day(s) cached, fetching {len(todo)}")
    if todo:
        with requests.Session() as sess, ThreadPoolExecutor(RT_THREADS) as ex:
            list(ex.map(lambda d: _fetch_rt_day(sess, d), todo))

    # the season must be contiguous from Jun 1; only a short unpublished tail is tolerated
    end = None
    for d in days:
        if not _rt_cached(d):
            break
        end = d
    if end is None or (asof - end).days > RT_MAX_SHORTFALL:
        gap = days[0] if end is None else end + timedelta(days=1)
        sys.exit(f"IMD real-time rain unavailable for {gap} (after retries); "
                 f"re-run later to resume -- {sum(map(_rt_cached, days))}/{len(days)} days are cached.")
    if end < asof:
        print(f"  [warn] IMD real-time rain not yet published after {end}; scoring to {end} instead of {asof}")
    d = imd.open_real_data("rain", f"{year}-06-01", end.isoformat(), str(RT_DIR))
    return _rain(d.get_xarray()), end


def onset_status(dep_pct):
    """Crude monsoon-onset proxy from the season-to-date rainfall departure."""
    if dep_pct is None:
        return "normal"
    if dep_pct <= -60:
        return "not_started"
    if dep_pct <= -25:
        return "delayed"
    if dep_pct >= 25:
        return "active"
    return "normal"


def _departure(cur_vals, clim_vals):
    """% departure of summed observed vs summed climatology; dry-region-safe.
    Clipped to [-100, 300]: -100 is physical (no rain), and a large surplus over a tiny
    climatological denominator (short windows in arid areas) is not informative uncapped."""
    cs, ls = float(np.nansum(cur_vals)), float(np.nansum(clim_vals))
    if ls < 0.5:
        return 0
    return int(max(-100, min(300, round((cs - ls) / ls * 100.0))))


def main():
    ap = argparse.ArgumentParser(description="Per-district observed rainfall departures from IMD gridded rainfall.")
    ap.add_argument("--districts", default=str(DEFAULT_DISTRICTS))
    ap.add_argument("--year", type=int, default=date.today().year)
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD (default: today - 3 days, IMD real-time lag).")
    ap.add_argument("--clim-years", type=int, nargs=2, metavar=("START", "END"), default=[1991, 2020])
    ap.add_argument("--out", default=str(PLOTS_DIR / "observed_departures.csv"))
    args = ap.parse_args()

    asof = pd.Timestamp(args.asof).date() if args.asof else (date.today() - timedelta(days=3))
    if asof <= date(args.year, 6, 1):
        sys.exit(f"asof {asof} is not after Jun 1 {args.year} — no season to score yet.")

    print(f"IMD observed departures: {args.year}-06-01 -> {asof}   (climatology {args.clim_years[0]}-{args.clim_years[1]})")
    clim = build_climatology(args.clim_years)               # (dayofyear, lat, lon)
    cur, asof = get_current(args.year, asof)                 # (time, lat, lon), same IMD grid
    lon, lat = _lonlat(cur)

    dates = pd.to_datetime(cur["time"].values)
    clim_at_dates = clim.sel(dayofyear=xr.DataArray(dates.dayofyear.values, dims="time"))

    gadm = gadm_districts()
    districts = pd.read_csv(args.districts)
    rows = []
    for _, d in districts.iterrows():
        state, name = d["state"], d["district"]
        geom, _ = resolve_geom(gadm, state, name, d["latitude"], d["longitude"])
        w, _, _ = region_weights(cur[lat].values, cur[lon].values, lat, lon, geom)
        w = w.fillna(0.0)
        cur_s = cur.weighted(w).mean((lat, lon)).values
        clim_s = clim_at_dates.weighted(w).mean((lat, lon)).values
        dep_season = _departure(cur_s, clim_s)
        rows.append({
            "state": state, "district": name,
            "rainfall_since_june_1_pct_departure": dep_season,
            "rainfall_last_7_days_pct_departure": _departure(cur_s[-7:], clim_s[-7:]),
            "rainfall_last_14_days_pct_departure": _departure(cur_s[-14:], clim_s[-14:]),
            "monsoon_onset_status": onset_status(dep_season),
            "obs_asof": asof.isoformat(),
        })

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"saved -> {args.out}  ({len(rows)} districts, asof {asof})")


if __name__ == "__main__":
    main()
